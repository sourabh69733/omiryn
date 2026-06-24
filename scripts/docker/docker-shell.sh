#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/docker/docker-common.sh
source "$SCRIPT_DIR/docker-common.sh"

IMAGE_NAME="${IMAGE_NAME:-omiryn}"
IMAGE_TAG="${IMAGE_TAG:-local}"
IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"
SANITIZED_ENV_FILE="$(docker_env_file)"
trap 'rm -f "$SANITIZED_ENV_FILE"' EXIT

run_args=(--rm -it --env-file "$SANITIZED_ENV_FILE")
while IFS= read -r arg; do
  run_args+=("$arg")
done < <(docker_data_mount_args)

docker run "${run_args[@]}" "$IMAGE" sh
