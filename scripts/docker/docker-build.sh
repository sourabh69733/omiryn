#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${IMAGE_NAME:-omiryn}"
IMAGE_TAG="${IMAGE_TAG:-local}"
IMAGE="${IMAGE_NAME}:${IMAGE_TAG}"

docker build -t "$IMAGE" .

echo "Built Docker image: $IMAGE"
