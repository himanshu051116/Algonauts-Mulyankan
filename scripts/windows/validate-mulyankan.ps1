$ErrorActionPreference = "Stop"

python -m compileall -q backend/app backend/scripts scripts/quality
ruff check backend/app backend/scripts backend/tests migrations/versions migrations/env.py scripts/quality
mypy backend/app
$env:PYTHONPATH = "backend"
pytest -q --cov=app --cov-report=term-missing --cov-fail-under=70

$previousDatabaseUrl = $env:DATABASE_URL
$previousExtensions = $env:ALLOWED_EXTENSIONS
try {
    $env:DATABASE_URL = "postgresql+asyncpg://release_user:release_pass@localhost:5432/mulyankan_release"
    $env:ALLOWED_EXTENSIONS = ".pdf,.docx,.txt"
    alembic -c migrations/alembic.ini upgrade head --sql | Out-Null
}
finally {
    $env:DATABASE_URL = $previousDatabaseUrl
    $env:ALLOWED_EXTENSIONS = $previousExtensions
}

npm run lint
npm run build
npm audit --audit-level=high

if (Get-Command docker -ErrorAction SilentlyContinue) {
    docker compose config -q
} else {
    python scripts/quality/validate_compose.py
}

Write-Host "All Mulyankan release quality gates passed." -ForegroundColor Green
