#!/usr/bin/env bash
# Genuine HAOS + Supervisor test in an ephemeral QEMU VM, no user secrets.
set -Eeuo pipefail

HAOS_VERSION="${HAOS_VERSION:-18.3}"
ADDON=local_mcphub
WORK_DIR="$(mktemp -d)"
VM_PID=""
cleanup() {
  if [[ -n "${VM_PID}" ]]; then
    kill "${VM_PID}" 2>/dev/null || true
    wait "${VM_PID}" 2>/dev/null || true
  fi
  mkdir -p "${GITHUB_WORKSPACE:-.}/haos-test-logs"
  for name in haos-console.log qemu.log; do
    if [[ -f "${WORK_DIR}/${name}" ]]; then
      cp "${WORK_DIR}/${name}" "${GITHUB_WORKSPACE:-.}/haos-test-logs/${name}"
    fi
  done
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

[[ -c /dev/kvm ]] || { echo "Real HAOS test requires /dev/kvm; refusing to skip" >&2; exit 1; }
sudo chmod 0666 /dev/kvm
url="https://os-artifacts.home-assistant.io/${HAOS_VERSION}/haos_ova-${HAOS_VERSION}.qcow2.xz"
echo "Downloading HAOS ${HAOS_VERSION}"
curl -fL --retry 4 --retry-all-errors --max-time 600 -o "${WORK_DIR}/haos.qcow2.xz" "${url}"
xz -dc "${WORK_DIR}/haos.qcow2.xz" > "${WORK_DIR}/haos.qcow2"
rm "${WORK_DIR}/haos.qcow2.xz"

ssh-keygen -q -t ed25519 -N '' -f "${WORK_DIR}/id_ed25519"
truncate -s 32M "${WORK_DIR}/config.img"
mkfs.vfat -n CONFIG "${WORK_DIR}/config.img" >/dev/null
mcopy -i "${WORK_DIR}/config.img" "${WORK_DIR}/id_ed25519.pub" ::authorized_keys

code=/usr/share/OVMF/OVMF_CODE_4M.fd
vars=/usr/share/OVMF/OVMF_VARS_4M.fd
[[ -r "$code" && -r "$vars" ]] || { echo "Missing OVMF UEFI firmware" >&2; exit 1; }
cp "$vars" "${WORK_DIR}/vars.fd"

qemu-system-x86_64 -machine q35,accel=kvm -cpu host -smp 3 -m 6144 \
  -display none -serial "file:${WORK_DIR}/haos-console.log" -no-reboot \
  -drive "if=pflash,format=raw,readonly=on,file=$code" \
  -drive "if=pflash,format=raw,file=${WORK_DIR}/vars.fd" \
  -drive "file=${WORK_DIR}/haos.qcow2,if=virtio,format=qcow2" \
  -device qemu-xhci \
  -drive "file=${WORK_DIR}/config.img,if=none,id=config,format=raw" \
  -device usb-storage,drive=config \
  -netdev 'user,id=network,hostfwd=tcp:127.0.0.1:22222-:22222' \
  -device virtio-net-pci,netdev=network \
  > "${WORK_DIR}/qemu.log" 2>&1 &
VM_PID="$!"

SSH_ARGS=(
  -p 22222 -i "${WORK_DIR}/id_ed25519"
  -o IdentitiesOnly=yes -o StrictHostKeyChecking=no
  -o UserKnownHostsFile=/dev/null -o ConnectTimeout=5 -o LogLevel=ERROR
)
remote() { ssh "${SSH_ARGS[@]}" root@127.0.0.1 "$@"; }

echo "Waiting for HAOS and Supervisor (up to 22 minutes)"
ready=false
for _ in $(seq 1 264); do
  kill -0 "${VM_PID}" 2>/dev/null || { echo "QEMU exited" >&2; cat "${WORK_DIR}/qemu.log"; exit 1; }
  if remote 'ha supervisor info >/dev/null 2>&1' 2>/dev/null; then
    ready=true
    break
  fi
  sleep 5
done
[[ "$ready" == true ]] || { echo "Supervisor not ready" >&2; exit 1; }

echo "Staging source inside HAOS Supervisor local add-ons"
remote 'mkdir -p /mnt/data/supervisor/addons/local/mcphub_ci'
tar -C MCPHub -cf - . | remote 'tar -xf - -C /mnt/data/supervisor/addons/local/mcphub_ci'
commit="$(git rev-parse HEAD)"
printf '%s\n' "$commit" | remote 'cat > /mnt/data/supervisor/addons/local/mcphub_ci/.haos-source-revision'

# Supervisor can be briefly unavailable while first-boot components update.
echo "Waiting for stable Supervisor add-on API"
reloaded=false
for _ in $(seq 1 120); do
  if remote 'ha addons reload >/dev/null 2>&1' 2>/dev/null; then
    reloaded=true
    break
  fi
  sleep 5
done
[[ "$reloaded" == true ]] || { echo "Supervisor add-on API never became ready" >&2; exit 1; }

found=false
for _ in $(seq 1 60); do
  if remote "ha addons info ${ADDON} >/dev/null 2>&1"; then found=true; break; fi
  sleep 5
done
[[ "$found" == true ]] || { echo "Supervisor failed to discover MCPHub" >&2; exit 1; }

info="$(remote "ha --raw-json addons info ${ADDON}")"
installed="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d.get("data",d).get("installed",False)).lower())' <<< "$info")"
if [[ "$installed" == true ]]; then
  remote "ha addons rebuild ${ADDON}"
else
  remote "ha addons install ${ADDON}"
fi
remote "ha addons start ${ADDON}" || remote "ha addons restart ${ADDON}"

wait_for_addon() {
  local state info
  for _ in $(seq 1 120); do
    info="$(remote "ha --raw-json addons info ${ADDON}" 2>/dev/null || true)"
    state="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("data",d).get("state",""))' <<< "$info" 2>/dev/null || true)"
    [[ "$state" == started ]] && return 0
    sleep 3
  done
  return 1
}
wait_for_health() {
  for _ in $(seq 1 80); do
    if remote "docker exec addon_${ADDON} curl --fail --silent --max-time 2 http://127.0.0.1:3000/health >/dev/null" 2>/dev/null; then
      return 0
    fi
    sleep 3
  done
  return 1
}
wait_for_addon && wait_for_health || {
  remote "ha addons logs ${ADDON}" || true
  echo "MCPHub failed to become healthy on HAOS" >&2
  exit 1
}

echo "Verifying generated Nginx rules and default-deny Tailscale origins"
remote "docker exec addon_${ADDON} nginx -t"
for port in 8094 8095; do
  result="$(remote "docker exec addon_${ADDON} curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:${port}/mcp")"
  [[ "$result" == 404 ]] || { echo "Origin ${port}: expected 404, got $result" >&2; exit 1; }
done

remote "ha addons restart ${ADDON}"
wait_for_addon && wait_for_health || { echo "MCPHub failed after Supervisor restart" >&2; exit 1; }

logs="$(remote "ha addons logs ${ADDON}" 2>&1)"
printf '%s\n' "$logs" > "${GITHUB_WORKSPACE:-.}/haos-test-logs-add-on.log"
grep -Fq "Build source revision: $commit" <<< "$logs" || {
  echo "MCPHub was not built from the checked-out revision" >&2
  exit 1
}
if grep -Eiq 'uncaught exception|unhandled rejection|FATAL|migration failed|SQLITE_CORRUPT' <<< "$logs"; then
  echo "Critical MCPHub runtime error" >&2
  exit 1
fi
echo "HAOS ${HAOS_VERSION} integration passed"
