#!/usr/bin/env sh
set -eu

repo_root="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"

if [ ! -f "$repo_root/.env" ]; then
  cp "$repo_root/.env.example" "$repo_root/.env"
  echo "已从 .env.example 创建本地 .env。"
fi

cd "$repo_root"
exec docker compose up --build

