#!/usr/bin/env bash
set -Eeuo pipefail

: "${HAOS_ADDONS_DIR:?Set HAOS_ADDONS_DIR to the local add-ons directory mounted from the dedicated HAOS test system}"

HA_CLI="${HA_CLI:-ha}"
ADDON_SLUG="local_mcphub"
TARGET_DIR="${HAOS_ADDONS_DIR%/}/mcphub_ci"

command -v rsync >/dev/null
command -v "${HA_CLI%% *}" >/dev/null

rm -rf "${TARGET_DIR}"
mkdir -p "${TARGET_DIR}"
rsync -a --delete "MCPHub/" "${TARGET_DIR}/"

${HA_CLI} addons reload

if ! ${HA_CLI} addons info "${ADDON_SLUG}" >/dev/null 2>&1; then
  echo "Home Assistant did not discover ${ADDON_SLUG} after copying the local add-on" >&2
  echo "Check HAOS_ADDONS_DIR and the dedicated runner's local add-on mount" >&2
  exit 1
fi

info_json="$(${HA_CLI} --raw-json addons info "${ADDON_SLUG}")"
installed="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(str(d.get("data", d).get("installed", False)).lower())' "${info_json}")"

if [[ "${installed}" != "true" ]]; then
  ${HA_CLI} addons install "${ADDON_SLUG}"
fi

${HA_CLI} addons restart "${ADDON_SLUG}" || ${HA_CLI} addons start "${ADDON_SLUG}"

for _ in $(seq 1 120); do
  info_json="$(${HA_CLI} --raw-json addons info "${ADDON_SLUG}")"
  state="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("data", d).get("state", ""))' "${info_json}")"
  [[ "${state}" == "started" ]] && break
  sleep 2
done

[[ "${state:-}" == "started" ]] || {
  ${HA_CLI} addons logs "${ADDON_SLUG}" || true
  echo "MCPHub add-on did not reach started state on HAOS" >&2
  exit 1
}

${HA_CLI} addons restart "${ADDON_SLUG}"
sleep 5

info_json="$(${HA_CLI} --raw-json addons info "${ADDON_SLUG}")"
state="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("data", d).get("state", ""))' "${info_json}")"
[[ "${state}" == "started" ]] || {
  echo "MCPHub add-on failed after Supervisor restart" >&2
  exit 1
}

if [[ -n "${HAOS_BASE_URL:-}" && -n "${HAOS_TOKEN:-}" ]]; then
  ingress_entry="$(python3 -c 'import json,sys; d=json.loads(sys.argv[1]); print(d.get("data", d).get("ingress_entry", ""))' "${info_json}")"

  if [[ -z "${ingress_entry}" ]]; then
    echo "HAOS did not report an ingress_entry for ${ADDON_SLUG}" >&2
    exit 1
  fi

  curl --fail --silent --show-error \
    --header "Authorization: Bearer ${HAOS_TOKEN}" \
    "${HAOS_BASE_URL%/}${ingress_entry}" >/dev/null
fi

logs="$(${HA_CLI} addons logs "${ADDON_SLUG}" 2>&1 || true)"
printf '%s\n' "${logs}"

if grep -Eiq 'uncaught exception|unhandled rejection|FATAL|migration failed|SQLITE_CORRUPT' <<<"${logs}"; then
  echo "Critical error pattern found in HAOS MCPHub logs" >&2
  exit 1
fi

printf '%s\n' "Dedicated HAOS MCPHub integration test passed"
