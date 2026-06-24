#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/docker/docker-common.sh
source "$SCRIPT_DIR/docker-common.sh"

IMAGE_NAME="${IMAGE_NAME:-omiryn}"
IMAGE_TAG="${IMAGE_TAG:-local}"
IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
CONTAINER_NAME="${CONTAINER_NAME:-omiryn-app}"
HOST_PORT="${HOST_PORT:-8080}"
CONTAINER_PORT="${PORT:-8080}"
SANITIZED_ENV_FILE="$(docker_env_file)"
echo "Docker santized env file: $SANITIZED_ENV_FILE"
trap 'rm -f "$SANITIZED_ENV_FILE"' EXIT

run_args=(
  --env-file "$SANITIZED_ENV_FILE"
  --name "$CONTAINER_NAME"
  -p "${HOST_PORT}:${CONTAINER_PORT}"
  -e "PORT=${CONTAINER_PORT}"
)

while IFS= read -r arg; do
  run_args+=("$arg")
done < <(docker_data_mount_args)

echo "Running Docker image: $IMAGE"
echo "Health URL: http://127.0.0.1:${HOST_PORT}/health"

docker run --rm "${run_args[@]}" "$IMAGE"
