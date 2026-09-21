#!/usr/bin/env bash
set -Eeuo pipefail

CURRENT_IMAGE="${1:-trilium-addon:test}"
BASE_BRANCH="${GITHUB_BASE_REF:-main}"
RUN_SUFFIX="${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}"
VOLUME="trilium-upgrade-${RUN_SUFFIX}"
CONTAINER="trilium-upgrade-app-${RUN_SUFFIX}"
PORT=18082
BASE_URL="http://127.0.0.1:${PORT}"

cleanup() {
  docker rm -f "${CONTAINER}" >/dev/null 2>&1 || true
  docker volume rm "${VOLUME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

wait_for_health() {
  for _ in $(seq 1 90); do
    local status
    status="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "${CONTAINER}")"
    case "${status}" in
      healthy) return 0 ;;
      unhealthy)
        docker logs "${CONTAINER}" >&2
        return 1
        ;;
    esac
    sleep 2
  done
  docker logs "${CONTAINER}" >&2
  return 1
}

start_container() {
  local image="$1"
  docker run --detach \
    --name "${CONTAINER}" \
    --publish "${PORT}:8080" \
    --env TRILIUM_DATA_DIR=/home/node/trilium-data \
    --env TRILIUM_GENERAL_NOAUTHENTICATION=true \
    --env TRILIUM_NETWORK_HOST=0.0.0.0 \
    --env TRILIUM_NETWORK_PORT=8080 \
    --volume "${VOLUME}:/home/node/trilium-data" \
    "${image}" >/dev/null
  wait_for_health
}

assert_initialized() {
  curl --fail --silent --show-error "${BASE_URL}/api/setup/status" | python3 -c '
import json, sys
payload = json.load(sys.stdin)
if payload.get("isInitialized") is not True:
    raise SystemExit(f"Database did not survive upgrade: {payload}")
print(payload)
'
}

determine_previous_image() {
  local ref="origin/${BASE_BRANCH}"
  local dockerfile
  local build_yaml
  local image

  dockerfile="$(git show "${ref}:TriliumNext Notes/Dockerfile" 2>/dev/null || true)"
  image="$(sed -nE \
    's#^FROM[[:space:]]+(docker\.io/triliumnext/trilium:v[^[:space:]]+)$#\1#p' \
    <<<"${dockerfile}" | head -n1)"

  if [[ -n "${image}" ]]; then
    printf '%s\n' "${image}"
    return 0
  fi

  # Legacy Home Assistant add-on layout: Dockerfile uses ARG BUILD_FROM and
  # build.yaml contains the architecture-specific upstream images.
  build_yaml="$(git show "${ref}:TriliumNext Notes/build.yaml" 2>/dev/null || true)"
  image="$(sed -nE \
    's#^[[:space:]]*amd64:[[:space:]]*["'"']?(docker\.io/triliumnext/trilium:v[^"'"'[:space:]]+)["'"']?[[:space:]]*$#\1#p' \
    <<<"${build_yaml}" | head -n1)"

  if [[ -n "${image}" ]]; then
    printf '%s\n' "${image}"
    return 0
  fi

  return 1
}

if ! git show-ref --verify --quiet "refs/remotes/origin/${BASE_BRANCH}"; then
  git fetch --depth=1 origin "${BASE_BRANCH}:refs/remotes/origin/${BASE_BRANCH}"
fi

if ! previous_image="$(determine_previous_image)"; then
  echo "Could not determine previous Trilium image from origin/${BASE_BRANCH}" >&2
  echo "Checked both Dockerfile and legacy build.yaml layouts" >&2
  exit 1
fi

if [[ ! "${previous_image}" =~ ^docker\.io/triliumnext/trilium:v[0-9] ]]; then
  echo "Refusing unexpected previous Trilium image: ${previous_image}" >&2
  exit 1
fi

echo "Upgrade test: ${previous_image} -> ${CURRENT_IMAGE}"
docker pull "${previous_image}" >/dev/null
docker volume create "${VOLUME}" >/dev/null

start_container "${previous_image}"
status="$(curl --fail --silent --show-error "${BASE_URL}/api/setup/status")"
if python3 -c 'import json,sys; raise SystemExit(0 if not json.loads(sys.argv[1]).get("isInitialized") else 1)' "${status}"; then
  code="$(curl --silent --show-error --output /dev/null --write-out '%{http_code}' \
    --request POST \
    --header 'Content-Type: application/json' \
    --data '{"locale":"en"}' \
    "${BASE_URL}/api/setup/new-document?skipDemoDb=1")"
  [[ "${code}" == "204" ]] || {
    echo "Old version initialization failed with HTTP ${code}" >&2
    exit 1
  }
fi
assert_initialized
docker exec "${CONTAINER}" test -s /home/node/trilium-data/document.db

docker rm -f "${CONTAINER}" >/dev/null
start_container "${CURRENT_IMAGE}"
assert_initialized
docker exec "${CONTAINER}" test -s /home/node/trilium-data/document.db
curl --fail --silent --show-error "${BASE_URL}/" | grep -qi '<html'

logs="$(docker logs "${CONTAINER}" 2>&1)"
printf '%s\n' "${logs}"
if grep -Eiq 'ERR_ERL_|UnhandledPromiseRejection|uncaught exception|SQLITE_CORRUPT|FATAL|migration failed' <<<"${logs}"; then
  echo "Critical error found after upgrade" >&2
  exit 1
fi
