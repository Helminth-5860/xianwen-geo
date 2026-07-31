$ErrorActionPreference = "Stop"

docker compose --profile rbac-test run --rm --build rbac-tests
if ($LASTEXITCODE -ne 0) {
    throw "PostgreSQL RBAC concurrency tests failed."
}