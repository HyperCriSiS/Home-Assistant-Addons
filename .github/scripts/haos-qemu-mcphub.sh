#!/usr/bin/env bash
# Ephemeral real Home Assistant OS/Supervisor test (no production credentials).
set -Eeuo pipefail
HAOS_VERSION="${HAOS_VERSION:-18.3}"
APP=local_mcphub
WORK="$(mktemp -d)"
VM_PID=""
cleanup() {
  if [[ -n "$VM_PID" ]]; then
    kill "$VM_PID" 2>/dev/null || true
    wait "$VM_PID" 2>/dev/null || true
  fi
  mkdir -p "${GITHUB_WORKSPACE:-.}/haos-test-logs"
  for name in haos-console.log qemu.log; do
    [[ ! -f "$WORK/$name" ]] || cp "$WORK/$name" "${GITHUB_WORKSPACE:-.}/haos-test-logs/$name"
  done
  rm -rf "$WORK"
}
trap cleanup EXIT

[[ -c /dev/kvm ]] || { echo "KVM not available; refusing to skip HAOS test" >&2; exit 1; }
sudo chmod 0666 /dev/kvm
url="https://os-artifacts.home-assistant.io/${HAOS_VERSION}/haos_ova-${HAOS_VERSION}.qcow2.xz"
echo "Downloading HAOS ${HAOS_VERSION}"
curl -fL --retry 4 --retry-all-errors --max-time 600 -o "$WORK/haos.qcow2.xz" "$url"
xz -dc "$WORK/haos.qcow2.xz" > "$WORK/haos.qcow2"
rm "$WORK/haos.qcow2.xz"

ssh-keygen -q -t ed25519 -N '' -f "$WORK/id_ed25519"
truncate -s 32M "$WORK/config.img"
mkfs.vfat -n CONFIG "$WORK/config.img" >/dev/null
mcopy -i "$WORK/config.img" "$WORK/id_ed25519.pub" ::authorized_keys
code=/usr/share/OVMF/OVMF_CODE_4M.fd
vars=/usr/share/OVMF/OVMF_VARS_4M.fd
[[ -r "$code" && -r "$vars" ]] || { echo "OVMF UEFI firmware unavailable" >&2; exit 1; }
cp "$vars" "$WORK/vars.fd"

qemu-system-x86_64 -machine q35,accel=kvm -cpu host -smp 3 -m 6144 \
  -display none -serial "file:$WORK/haos-console.log" -no-reboot \
  -drive "if=pflash,format=raw,readonly=on,file=$code" \
  -drive "if=pflash,format=raw,file=$WORK/vars.fd" \
  -drive "file=$WORK/haos.qcow2,if=virtio,format=qcow2" \
  -device qemu-xhci -drive "file=$WORK/config.img,if=none,id=config,format=raw" \
  -device usb-storage,drive=config \
  -netdev 'user,id=network,hostfwd=tcp:127.0.0.1:22222-:22222' \
  -device virtio-net-pci,netdev=network \
  > "$WORK/qemu.log" 2>&1 &
VM_PID="$!"
SSH_ARGS=(
  -p 22222 -i "$WORK/id_ed25519" -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
  -o ConnectTimeout=5 -o LogLevel=ERROR
)
remote() { ssh "${SSH_ARGS[@]}" root@127.0.0.1 "$@"; }

echo "Waiting for HAOS Supervisor bootstrap"
ready=false
for _ in $(seq 1 264); do
  kill -0 "$VM_PID" 2>/dev/null || { echo "QEMU exited" >&2; cat "$WORK/qemu.log"; exit 1; }
  if remote 'ha supervisor info >/dev/null 2>&1' 2>/dev/null; then ready=true; break; fi
  sleep 5
done
[[ "$ready" == true ]] || { echo "Supervisor not ready after 22 minutes" >&2; exit 1; }

# Supervisor 2026+ renamed its local app store from addons/local to apps/local.
# Writing to the legacy path can make the store reload succeed but miss the app.
app_dir=/mnt/data/supervisor/apps/local/mcphub_ci
echo "Staging MCPHub source in current Supervisor apps/local store"
remote "mkdir -p $app_dir"
tar -C MCPHub -cf - . | remote "tar -xf - -C $app_dir"
commit="$(git rev-parse HEAD)"
printf '%s\n' "$commit" | remote "cat > $app_dir/.haos-source-revision"

echo "Waiting for Supervisor apps API"
reloaded=false
for _ in $(seq 1 120); do
  if remote 'ha apps reload >/dev/null 2>&1' 2>/dev/null; then reloaded=true; break; fi
  sleep 5
done
[[ "$reloaded" == true ]] || { echo "Supervisor apps API not available" >&2; exit 1; }

found=false
for _ in $(seq 1 60); do
  if remote "ha apps info $APP >/dev/null 2>&1"; then found=true; break; fi
  sleep 5
done
if [[ "$found" != true ]]; then
  remote 'ls -l /mnt/data/supervisor/apps/local/ /mnt/data/supervisor/apps/local/mcphub_ci/' || true
  remote 'ha apps list' || true
  echo "Supervisor did not discover MCPHub app" >&2
  exit 1
fi

info="$(remote "ha --raw-json apps info $APP")"
installed="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d.get("data",d).get("installed",False)).lower())' <<< "$info")"
if [[ "$installed" == true ]]; then
  remote "ha apps rebuild $APP"
else
  remote "ha apps install $APP"
fi
remote "ha apps start $APP" || remote "ha apps restart $APP"

wait_for_app() {
  local state info
  for _ in $(seq 1 120); do
    info="$(remote "ha --raw-json apps info $APP" 2>/dev/null || true)"
    state="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("data",d).get("state",""))' <<< "$info" 2>/dev/null || true)"
    [[ "$state" == started ]] && return 0
    sleep 3
  done
  return 1
}
wait_for_health() {
  for _ in $(seq 1 80); do
    if remote "docker exec addon_$APP curl --fail --silent --max-time 2 http://127.0.0.1:3000/health >/dev/null" 2>/dev/null; then return 0; fi
    sleep 3
  done
  return 1
}
wait_for_app && wait_for_health || {
  remote "ha apps logs $APP" || true
  echo "MCPHub failed to become healthy on HAOS" >&2
  exit 1
}

echo "Checking Nginx and disabled remote origins inside Supervisor-managed app"
remote "docker exec addon_$APP nginx -t"
for port in 8094 8095; do
  result="$(remote "docker exec addon_$APP curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:$port/mcp")"
  [[ "$result" == 404 ]] || { echo "Origin $port: expected 404, got $result" >&2; exit 1; }
done

remote "ha apps restart $APP"
wait_for_app && wait_for_health || { echo "MCPHub failed after Supervisor restart" >&2; exit 1; }
logs="$(remote "ha apps logs $APP" 2>&1)"
printf '%s\n' "$logs" > "${GITHUB_WORKSPACE:-.}/haos-test-logs-app.log"
grep -Fq "Build source revision: $commit" <<< "$logs" || {
  echo "HAOS did not execute the checked-out source" >&2
  exit 1
}
if grep -Eiq 'uncaught exception|unhandled rejection|FATAL|migration failed|SQLITE_CORRUPT' <<< "$logs"; then
  echo "Critical MCPHub runtime error" >&2
  exit 1
fi
echo "HAOS ${HAOS_VERSION} Supervisor MCPHub test passed"
