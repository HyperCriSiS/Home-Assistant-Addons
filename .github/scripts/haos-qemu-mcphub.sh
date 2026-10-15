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
# Remote command arguments intentionally expand locally before SSH transmits them.
# shellcheck disable=SC2029
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

# Validate the actual manifest with the running Supervisor, not just YAML lint.
# A known-good control from the last green HAOS VM test is installed next to
# the current PR source to distinguish candidate schema failures from VM issues.
BASELINE_SHA="1de97ef8e9bc8c68dd216e8d9aeabe52fa5e50e5"
control_slug="mcphub_ci_control"
control_dir="/mnt/data/supervisor/apps/local/$control_slug"
remote "mkdir -p $control_dir"
tar -C MCPHub -cf - . | remote "tar -xf - -C $control_dir"
git show "$BASELINE_SHA:MCPHub/config.yaml" \
  | sed 's/^slug: mcphub$/slug: mcphub_ci_control/' \
  | remote "cat > $control_dir/config.yaml"

check_schema() {
  local slug="$1"
  echo "Supervisor schema validation: $slug"
  remote "docker exec hassio_supervisor python3 -c 'from pathlib import Path; import yaml; from supervisor.apps.validate import SCHEMA_APP_CONFIG; p=Path(\"/data/apps/local/$slug/config.yaml\"); SCHEMA_APP_CONFIG(yaml.safe_load(p.read_text())); print(\"VALID_SUPERVISOR_APP_CONFIG:\", p)'"
}
check_schema "$control_slug" || {
  echo "Even the known-good control failed Supervisor schema validation." >&2
  exit 1
}
candidate_schema_ok=true
if ! check_schema mcphub_ci; then
  echo "Candidate MCPHub configuration failed the live Supervisor schema." >&2
  candidate_schema_ok=false
fi

echo "Waiting for Supervisor updater gate before app-store refresh"
# The first HAOS boot can block StoreManager.reload until Supervisor is updated.
# Retry only on errors, never issue overlapping refreshes after a success.
reload_ok=false
supervisor_update_requested=false
for attempt in $(seq 1 100); do
  if output="$(remote 'ha store reload' 2>&1)"; then
    reload_ok=true
    echo "Supervisor app store refreshed successfully"
    break
  fi
  if [[ "$output" == *"supervisor needs to be updated first"* ]]; then
    if [[ "$supervisor_update_requested" == false && "$attempt" -ge 3 ]]; then
      echo "Requesting Supervisor update on disposable HAOS test VM"
      remote 'ha supervisor update' || true
      supervisor_update_requested=true
    fi
  else
    echo "Store refresh not ready (attempt $attempt): $output"
  fi
  sleep 10
done
if [[ "$reload_ok" != true ]]; then
  echo "Supervisor never allowed a store refresh" >&2
  remote 'ha supervisor info' || true
  exit 1
fi

echo "Waiting for known-good control and candidate in the Supervisor STORE"
# /addons/{slug}/info is an installed-app endpoint; store registration should
# be verified with /store/addons before the candidate is installed.
store_local_slugs() {
  remote 'ha --raw-json store apps' | python3 -c '
import json, sys
payload = json.load(sys.stdin)
payload = payload.get("data", payload)
if isinstance(payload, dict):
    items = payload.get("addons", payload.get("apps", []))
elif isinstance(payload, list):
    items = payload
else:
    items = []
print(" ".join(str(x.get("slug", "")) for x in items if isinstance(x, dict) and str(x.get("slug", "")).startswith("local_")))
'
}
control_found=false
found=false
for attempt in $(seq 1 90); do
  slugs="$(store_local_slugs 2>/dev/null || true)"
  if [[ " $slugs " == *" local_mcphub_ci_control "* ]]; then control_found=true; fi
  if [[ " $slugs " == *" $APP "* ]]; then found=true; fi
  if [[ "$control_found" == true && "$found" == true ]]; then
    echo "Supervisor local store discovered: $slugs"
    break
  fi
  if (( attempt % 10 == 0 )); then
    echo "Store discovery attempt $attempt: local slugs '$slugs'"
  fi
  sleep 5
done
if [[ "$control_found" != true || "$found" != true ]]; then
  echo "Local store discovery incomplete (known-good=$control_found candidate=$found)." >&2
  echo "Discovered store slugs: $(store_local_slugs || true)"
  remote 'ha store apps' || true
  remote 'ha supervisor logs' || true
  remote 'docker logs --since 10m hassio_supervisor 2>&1 | grep -Ei "mcphub|local|schema|invalid|error|warning|reload|store"' || true
  exit 1
fi
echo "Both manifest variants discovered by Supervisor"
[[ "$candidate_schema_ok" == true ]] || {
  echo "Candidate configuration was rejected by the live Supervisor schema." >&2
  exit 1
}

info="$(remote "ha --raw-json apps info $APP")"
installed="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d.get("data",d).get("installed",False)).lower())' <<< "$info")"
if [[ "$installed" == true ]]; then
  remote "ha apps rebuild $APP"
else
  remote "ha store apps install $APP"
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
    if remote "docker exec app_$APP curl --fail --silent --max-time 2 http://127.0.0.1:3000/health >/dev/null" 2>/dev/null; then return 0; fi
    sleep 3
  done
  return 1
}
if ! wait_for_app || ! wait_for_health; then
  remote "ha apps logs $APP" || true
  echo "MCPHub failed to become healthy on HAOS" >&2
  exit 1
fi

echo "Checking Nginx, isolated Unix sockets and absence of host-published origin ports"
remote "docker exec app_$APP nginx -t"
for mode in serve funnel; do
  remote "docker exec app_$APP test -S /share/mcphub/tailscale-$mode.sock"
  result="$(remote "docker exec app_$APP curl --silent --unix-socket /share/mcphub/tailscale-$mode.sock --output /dev/null --write-out '%{http_code}' http://localhost/mcp")"
  [[ "$result" == 404 ]] || { echo "Tailscale $mode origin: expected 404, got $result" >&2; exit 1; }
done
port_bindings="$(remote "docker inspect -f '{{json .HostConfig.PortBindings}}' app_$APP")"
[[ "$port_bindings" != *8094* && "$port_bindings" != *8095* ]] || {
  echo "Unwanted public Tailscale origin port: $port_bindings" >&2
  exit 1
}
# Simulate the host-network Tailscale app with /share mounted read-only.
# Remote Docker command expansion intentionally happens in the HAOS guest.
# shellcheck disable=SC2016
remote 'docker run --rm --network host --volume /mnt/data/supervisor/share:/share:ro --entrypoint curl "$(docker inspect -f "{{.Image}}" app_local_mcphub)" --silent --unix-socket /share/mcphub/tailscale-serve.sock --output /dev/null --write-out "%{http_code}" http://localhost/mcp' | grep -qx 404

remote "ha apps restart $APP"
if ! wait_for_app || ! wait_for_health; then
  echo "MCPHub failed after Supervisor restart" >&2
  exit 1
fi
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
