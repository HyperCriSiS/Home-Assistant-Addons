#!/usr/bin/env bash
# Ephemeral genuine HAOS + Supervisor integration test (no production credentials).
set -Eeuo pipefail
HAOS_VERSION="${HAOS_VERSION:-18.3}"
ADDON="local_mcphub"
WORK_DIR="$(mktemp -d)"
VM_PID=""
cleanup() {
  if [[ -n "${VM_PID}" ]]; then
    kill "${VM_PID}" 2>/dev/null || true
    wait "${VM_PID}" 2>/dev/null || true
  fi
  if [[ -f "${WORK_DIR}/haos-console.log" ]]; then
    mkdir -p "${GITHUB_WORKSPACE:-.}/haos-test-logs"
    cp "${WORK_DIR}/haos-console.log" "${GITHUB_WORKSPACE:-.}/haos-test-logs/console.log"
  fi
  if [[ -f "${WORK_DIR}/qemu.log" ]]; then
    mkdir -p "${GITHUB_WORKSPACE:-.}/haos-test-logs"
    cp "${WORK_DIR}/qemu.log" "${GITHUB_WORKSPACE:-.}/haos-test-logs/qemu.log"
  fi
  rm -rf "${WORK_DIR}"
}
trap cleanup EXIT

if [[ ! -c /dev/kvm ]]; then
  echo "Real HAOS testing requires /dev/kvm; not silently skipping" >&2
  exit 1
fi
sudo chmod 0666 /dev/kvm

image_url="https://os-artifacts.home-assistant.io/${HAOS_VERSION}/haos_ova-${HAOS_VERSION}.qcow2.xz"
echo "Downloading pinned HAOS ${HAOS_VERSION} VM image"
curl --fail --location --retry 4 --retry-all-errors --max-time 600 \
  --output "${WORK_DIR}/haos.qcow2.xz" "${image_url}"
xz --decompress --stdout "${WORK_DIR}/haos.qcow2.xz" > "${WORK_DIR}/haos.qcow2"
rm -f "${WORK_DIR}/haos.qcow2.xz"

ssh-keygen -q -t ed25519 -N '' -f "${WORK_DIR}/id_ed25519"
truncate -s 32M "${WORK_DIR}/config.img"
mkfs.vfat -n CONFIG "${WORK_DIR}/config.img" >/dev/null
mcopy -i "${WORK_DIR}/config.img" "${WORK_DIR}/id_ed25519.pub" ::authorized_keys

ovmf_code="/usr/share/OVMF/OVMF_CODE_4M.fd"
ovmf_vars="/usr/share/OVMF/OVMF_VARS_4M.fd"
[[ -r "${ovmf_code}" && -r "${ovmf_vars}" ]] || {
  echo "OVMF firmware not found on GitHub runner" >&2
  exit 1
}
cp "${ovmf_vars}" "${WORK_DIR}/ovmf-vars.fd"
qemu-system-x86_64 \
  -machine q35,accel=kvm -cpu host -smp 3 -m 6144 \
  -display none -serial "file:${WORK_DIR}/haos-console.log" -no-reboot \
  -drive "if=pflash,format=raw,readonly=on,file=${ovmf_code}" \
  -drive "if=pflash,format=raw,file=${WORK_DIR}/ovmf-vars.fd" \
  -drive "file=${WORK_DIR}/haos.qcow2,if=virtio,format=qcow2" \
  -device qemu-xhci \
  -drive "file=${WORK_DIR}/config.img,if=none,id=config,format=raw" \
  -device usb-storage,drive=config \
  -netdev 'user,id=network,hostfwd=tcp:127.0.0.1:22222-:22222' \
  -device virtio-net-pci,netdev=network \
  > "${WORK_DIR}/qemu.log" 2>&1 &
VM_PID="$!"

SSH_ARGS=(
  -p 22222 -i "${WORK_DIR}/id_ed25519" -o IdentitiesOnly=yes
  -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
  -o ConnectTimeout=5 -o LogLevel=ERROR
)
remote() { ssh "${SSH_ARGS[@]}" root@127.0.0.1 "$@"; }

# First boot imports the SSH key from the attached CONFIG USB drive.
echo "Waiting for HAOS Supervisor (maximum 22 minutes)"
ready=false
for _ in $(seq 1 264); do
  kill -0 "${VM_PID}" 2>/dev/null || { echo "HAOS VM exited" >&2; cat "${WORK_DIR}/qemu.log"; exit 1; }
  if remote 'ha supervisor info >/dev/null 2>&1' 2>/dev/null; then
    ready=true
    break
  fi
  sleep 5
done
[[ "${ready}" == true ]] || { echo "HAOS Supervisor never became ready" >&2; exit 1; }

echo "Installing candidate MCPHub source as local Supervisor add-on"
remote 'mkdir -p /mnt/data/supervisor/addons/local/mcphub_ci'
tar -C MCPHub -cf - . | remote 'tar -xf - -C /mnt/data/supervisor/addons/local/mcphub_ci'
commit="$(git rev-parse HEAD)"
printf '%s\n' "${commit}" | remote 'cat > /mnt/data/supervisor/addons/local/mcphub_ci/.haos-source-revision'
remote 'ha addons reload'
found=false
for _ in $(seq 1 30); do
  if remote "ha addons info ${ADDON} >/dev/null 2>&1"; then found=true; break; fi
  sleep 3
done
[[ "${found}" == true ]] || { echo "Supervisor did not discover MCPHub" >&2; exit 1; }

info="$(remote "ha --raw-json addons info ${ADDON}")"
installed="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(str(d.get("data",d).get("installed",False)).lower())' <<< "${info}")"
if [[ "${installed}" == true ]]; then
  remote "ha addons rebuild ${ADDON}"
else
  remote "ha addons install ${ADDON}"
fi
remote "ha addons start ${ADDON}" || remote "ha addons restart ${ADDON}"

wait_for_addon() {
  local state info
  for _ in $(seq 1 90); do
    info="$(remote "ha --raw-json addons info ${ADDON}" 2>/dev/null || true)"
    state="$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("data",d).get("state",""))' <<< "${info}" 2>/dev/null || true)"
    [[ "${state}" == started ]] && return 0
    sleep 3
  done
  return 1
}
wait_for_addon || { remote "ha addons logs ${ADDON}" || true; echo "MCPHub start failed" >&2; exit 1; }

echo "Checking Supervisor-managed MCPHub service and isolated Tailscale ports"
remote "docker exec addon_${ADDON} nginx -t"
remote "docker exec addon_${ADDON} curl --fail --silent http://127.0.0.1:3000/health >/dev/null"
for port in 8094 8095; do
  code="$(remote "docker exec addon_${ADDON} curl --silent --output /dev/null --write-out '%{http_code}' http://127.0.0.1:${port}/mcp")"
  [[ "${code}" == 404 ]] || { echo "Tailscale origin ${port}: expected 404, got ${code}" >&2; exit 1; }
done

remote "ha addons restart ${ADDON}"
wait_for_addon || { echo "Supervisor restart failed" >&2; exit 1; }
remote "docker exec addon_${ADDON} curl --fail --silent http://127.0.0.1:3000/health >/dev/null"

logs="$(remote "ha addons logs ${ADDON}" 2>&1)"
printf '%s\n' "${logs}" > "${GITHUB_WORKSPACE:-.}/haos-test-logs-add-on.log"
if ! grep -Fq "Build source revision: ${commit}" <<< "${logs}"; then
  echo "HAOS did not run the tested source revision" >&2
  exit 1
fi
if grep -Eiq 'uncaught exception|unhandled rejection|FATAL|migration failed|SQLITE_CORRUPT' <<< "${logs}"; then
  echo "Critical MCPHub runtime error" >&2
  exit 1
fi
echo "HAOS ${HAOS_VERSION} Supervisor integration passed"
