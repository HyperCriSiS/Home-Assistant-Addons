#!/usr/bin/env bash
set -Eeuo pipefail

IMAGE="${1:-trilium-addon:test}"
RUN_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
NETWORK="trilium-ingress-${RUN_SUFFIX}"
VOLUME="trilium-data-${RUN_SUFFIX}"
APP_CONTAINER="trilium-app-${RUN_SUFFIX}"
PROXY_CONTAINER="trilium-proxy-${RUN_SUFFIX}"
TMP_DIR="$(mktemp -d)"
DIRECT_URL="http://127.0.0.1:18081"
PROXY_URL="http://127.0.0.1:18080"

cleanup() {
  docker rm -f "${PROXY_CONTAINER}" "${APP_CONTAINER}" >/dev/null 2>&1 || true
  docker network rm "${NETWORK}" >/dev/null 2>&1 || true
  docker volume rm "${VOLUME}" >/dev/null 2>&1 || true
  rm -rf "${TMP_DIR}"
}
trap cleanup EXIT

wait_for_health() {
  local container="$1"
  local attempts=90
  for _ in $(seq 1 "${attempts}"); do
    local status
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${container}")"
    case "${status}" in
      healthy)
        return 0
        ;;
      unhealthy)
        docker logs "${container}" >&2
        return 1
        ;;
    esac
    sleep 2
  done
  docker logs "${container}" >&2
  echo "Container did not become healthy in time" >&2
  return 1
}

assert_initialized() {
  local url="$1"
  curl --fail --silent --show-error "${url}/api/setup/status" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
if payload.get("isInitialized") is not True:
    raise SystemExit(f"Trilium is not initialized: {payload}")
print(payload)
'
}

assert_clean_logs() {
  local logs
  logs="$(docker logs "${APP_CONTAINER}" 2>&1)"
  printf '%s\n' "${logs}"
  if grep -Eiq 'ERR_ERL_|UnhandledPromiseRejection|uncaught exception|SQLITE_CORRUPT|FATAL|EADDRINUSE' <<<"${logs}"; then
    echo "Critical error pattern found in Trilium logs" >&2
    return 1
  fi
  if grep -Eq '(^|[^0-9])5[0-9]{2} (GET|POST|PUT|DELETE|PATCH) ' <<<"${logs}"; then
    echo "HTTP 5xx response found in Trilium logs" >&2
    return 1
  fi
}

docker network create --subnet 172.30.32.0/24 "${NETWORK}" >/dev/null
docker volume create "${VOLUME}" >/dev/null

docker run --detach \
  --name "${APP_CONTAINER}" \
  --network "${NETWORK}" \
  --ip 172.30.32.10 \
  --publish 18081:8080 \
  --env TRILIUM_DATA_DIR=/home/node/trilium-data \
  --env TRILIUM_GENERAL_NOAUTHENTICATION=true \
  --env TRILIUM_NETWORK_HOST=0.0.0.0 \
  --env TRILIUM_NETWORK_PORT=8080 \
  --env TRILIUM_NETWORK_TRUSTEDREVERSEPROXY=172.30.32.2 \
  --volume "${VOLUME}:/home/node/trilium-data" \
  "${IMAGE}" >/dev/null

wait_for_health "${APP_CONTAINER}"
curl --fail --silent --show-error "${DIRECT_URL}/api/health-check" >/dev/null

setup_status="$(curl --fail --silent --show-error "${DIRECT_URL}/api/setup/status")"
if ! python3 -c 'import json,sys; raise SystemExit(0 if not json.loads(sys.argv[1]).get("isInitialized") else 1)' "${setup_status}"; then
  echo "Expected a fresh, uninitialized Trilium database" >&2
  exit 1
fi

http_code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{"locale":"en"}' \
  "${DIRECT_URL}/api/setup/new-document?skipDemoDb=1")"
if [[ "${http_code}" != "204" ]]; then
  echo "Initializing a new Trilium document returned HTTP ${http_code}" >&2
  docker logs "${APP_CONTAINER}" >&2
  exit 1
fi
assert_initialized "${DIRECT_URL}"

cat > "${TMP_DIR}/default.conf" <<'NGINX'
map $http_upgrade $connection_upgrade {
    default upgrade;
    '' close;
}

server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://172.30.32.10:8080;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto http;
        proxy_set_header X-Ingress-Path /api/hassio_ingress/ci/;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $connection_upgrade;
        proxy_read_timeout 60s;
    }
}
NGINX

docker run --detach \
  --name "${PROXY_CONTAINER}" \
  --network "${NETWORK}" \
  --ip 172.30.32.2 \
  --publish 18080:80 \
  --volume "${TMP_DIR}/default.conf:/etc/nginx/conf.d/default.conf:ro" \
  docker.io/library/nginx:1.28.0-alpine >/dev/null

for _ in $(seq 1 30); do
  if curl --fail --silent --show-error "${PROXY_URL}/api/health-check" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

curl --fail --silent --show-error "${PROXY_URL}/api/health-check" >/dev/null
assert_initialized "${PROXY_URL}"
curl --fail --silent --show-error "${PROXY_URL}/" | grep -qi '<html'

WEBSOCKET_URL="ws://127.0.0.1:18080/" python3 .github/scripts/test_websocket.py

BASE_URL="${PROXY_URL}" npm --prefix .github/tests/e2e test

# Verify persistence across an ordinary container restart using the same Home Assistant data volume.
docker rm -f "${APP_CONTAINER}" >/dev/null

docker run --detach \
  --name "${APP_CONTAINER}" \
  --network "${NETWORK}" \
  --ip 172.30.32.10 \
  --publish 18081:8080 \
  --env TRILIUM_DATA_DIR=/home/node/trilium-data \
  --env TRILIUM_GENERAL_NOAUTHENTICATION=true \
  --env TRILIUM_NETWORK_HOST=0.0.0.0 \
  --env TRILIUM_NETWORK_PORT=8080 \
  --env TRILIUM_NETWORK_TRUSTEDREVERSEPROXY=172.30.32.2 \
  --volume "${VOLUME}:/home/node/trilium-data" \
  "${IMAGE}" >/dev/null

wait_for_health "${APP_CONTAINER}"
assert_initialized "${DIRECT_URL}"
docker exec "${APP_CONTAINER}" test -s /home/node/trilium-data/document.db
assert_clean_logs
