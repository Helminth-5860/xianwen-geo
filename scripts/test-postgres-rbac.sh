#!/usr/bin/env bash
set -euo pipefail

docker compose --profile rbac-test run --rm --build rbac-tests