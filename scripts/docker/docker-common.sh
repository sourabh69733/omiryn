#!/usr/bin/env bash
set -euo pipefail

default_env_file() {
  if [ -f "scripts/docker/.env" ]; then
    echo "scripts/docker/.env"
  else
    echo ".env"
  fi
}

docker_env_file() {
  local source_file="${ENV_FILE:-$(default_env_file)}"
  local output_file
  output_file="$(mktemp "${TMPDIR:-/tmp}/omiryn-docker-env.XXXXXX")"

  if [ -f "$source_file" ]; then
    python - "$source_file" "$output_file" <<'PY'
from __future__ import annotations

import sys

source_path, output_path = sys.argv[1], sys.argv[2]


def clean_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        value = value[1:-1]
    return value


with open(source_path, "r", encoding="utf-8") as source, open(
    output_path, "w", encoding="utf-8"
) as output:
    for raw_line in source:
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = clean_value(value)
        if key == "DATABASE_URL":
            value = value.replace("@localhost:", "@host.docker.internal:")
            value = value.replace("@127.0.0.1:", "@host.docker.internal:")
        output.write(f"{key}={value}\n")
PY
  fi

  echo "$output_file"
}

docker_data_mount_args() {
  if [ -d "data" ]; then
    printf "%s\n%s\n" "-v" "$PWD/data:/app/data"
  fi
}
