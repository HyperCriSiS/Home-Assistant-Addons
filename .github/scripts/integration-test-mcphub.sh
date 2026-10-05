#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE="${1:-mcphub-addon:test}"
NETWORK="mcphub-ci-${RANDOM}"
CONTAINER="mcphub-addon-test-${RANDOM}"
VOLUME="mcphub-data-${RANDOM}"
INGRESS_IMAGE="curlimages/curl:8.16.0"
INGRESS_PATH="/api/hassio_ingress/mcphub-test"

cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  docker volume rm "${VOLUME}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker network create --subnet 172.30.32.0/24 "${NETWORK}" >/dev/null
docker volume create "${VOLUME}" >/dev/null

write_options() {
  docker run --rm \
    --volume "${VOLUME}:/data" \
    alpine:3.22 \
    sh -c 'cat > /data/options.json <<EOF
{"tunnel_enabled":false,"openai_runtime_api_key":"","tunnel_id":"","tunnel_mcp_path":"/mcp","tunnel_log_level":"info"}
EOF'
}

start_addon() {
  docker run -d \
    --name "${CONTAINER}" \
    --network "${NETWORK}" \
    --ip 172.30.32.3 \
    --volume "${VOLUME}:/data" \
    "${IMAGE}" >/dev/null
}

wait_ready() {
  for _ in $(seq 1 120); do
    if docker exec "${CONTAINER}" curl --silent --fail --max-time 1 \
      http://127.0.0.1:3000/health >/dev/null 2>&1; then
      return 0
    fi

    if [[ "$(docker inspect -f '{{.State.Running}}' "${CONTAINER}")" != "true" ]]; then
      docker logs "${CONTAINER}" || true
      echo "MCPHub test container exited during startup" >&2
      return 1
    fi

    sleep 1
  done

  docker logs "${CONTAINER}" || true
  echo "MCPHub did not become ready" >&2
  return 1
}

ingress_curl() {
  docker run --rm \
    --network "${NETWORK}" \
    --ip 172.30.32.2 \
    "${INGRESS_IMAGE}" \
    --header "X-Remote-User-Id: test-user-id" \
    --header "X-Remote-User-Name: test-admin" \
    --header "X-Remote-User-Display-Name: Test Admin" \
    "$@"
}

write_options
start_addon
wait_ready

config_json="$(ingress_curl --fail --silent --show-error \
  --header "X-Ingress-Path: ${INGRESS_PATH}" \
  "http://${CONTAINER}:8099/config")"

python3 - "${config_json}" "${INGRESS_PATH}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
expected = sys.argv[2]
actual = payload.get("data", {}).get("basePath")
if actual != expected:
    raise SystemExit(f"Unexpected Ingress basePath: {actual!r}, expected {expected!r}")
PY

ingress_curl --fail --silent --show-error \
  --header "X-Ingress-Path: ${INGRESS_PATH}" \
  "http://${CONTAINER}:8099/" >/dev/null

user_json="$(ingress_curl --fail --silent --show-error \
  --header "X-Ingress-Path: ${INGRESS_PATH}" \
  "http://${CONTAINER}:8099/api/better-auth/user")"

python3 - "${user_json}" <<'PY'
import json
import sys

payload = json.loads(sys.argv[1])
user = payload.get("user", {})
if payload.get("success") is not True:
    raise SystemExit("Home Assistant SSO user endpoint did not succeed")
if user.get("username") != "test-admin":
    raise SystemExit(f"Unexpected Home Assistant SSO username: {user.get('username')!r}")
if user.get("isAdmin") is not True:
    raise SystemExit("Home Assistant Ingress user was not mapped to MCPHub admin")
PY

if docker exec "${CONTAINER}" curl --fail --silent --max-time 2 \
  --header "X-Remote-User-Id: spoofed-user" \
  --header "X-Remote-User-Name: spoofed-admin" \
  http://127.0.0.1:3000/api/servers >/dev/null 2>&1; then
  echo "MCPHub trusted Home Assistant identity headers without the private proxy secret" >&2
  exit 1
fi

if docker run --rm \
  --network "${NETWORK}" \
  --ip 172.30.32.4 \
  "${INGRESS_IMAGE}" \
  --fail --silent --max-time 2 \
  "http://${CONTAINER}:8099/health" >/dev/null 2>&1; then
  echo "Ingress adapter accepted a non-Supervisor source address" >&2
  exit 1
fi

if docker run --rm \
  --network "${NETWORK}" \
  --ip 172.30.32.5 \
  "${INGRESS_IMAGE}" \
  --fail --silent --max-time 2 \
  "http://${CONTAINER}:3000/health" >/dev/null 2>&1; then
  echo "MCPHub port 3000 is reachable from another container" >&2
  exit 1
fi

token_before="$(docker exec "${CONTAINER}" cat /data/secrets/mcphub_tunnel_token)"
[[ -n "${token_before}" ]]

docker rm -f "${CONTAINER}" >/dev/null
start_addon
wait_ready

token_after="$(docker exec "${CONTAINER}" cat /data/secrets/mcphub_tunnel_token)"
[[ "${token_before}" == "${token_after}" ]] || {
  echo "Persistent internal bearer token changed after restart" >&2
  exit 1
}

logs="$(docker logs "${CONTAINER}" 2>&1 || true)"
printf '%s\n' "${logs}"

if grep -Eiq 'uncaught exception|unhandled rejection|FATAL|migration failed|SQLITE_CORRUPT' <<<"${logs}"; then
  echo "Critical error pattern found in MCPHub logs" >&2
  exit 1
fi

printf '%s\n' "MCPHub container integration test passed"
