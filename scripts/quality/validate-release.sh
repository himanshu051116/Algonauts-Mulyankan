#!/usr/bin/env sh
set -eu

python -m compileall -q backend/app backend/scripts scripts/quality
ruff check backend/app backend/scripts backend/tests migrations/versions migrations/env.py scripts/quality
mypy backend/app
PYTHONPATH=backend pytest -q --cov=app --cov-report=term-missing --cov-fail-under=70

DATABASE_URL='postgresql+asyncpg://release_user:release_pass@localhost:5432/mulyankan_release' \
ALLOWED_EXTENSIONS='.pdf,.docx,.txt' \
  alembic -c migrations/alembic.ini upgrade head --sql >/tmp/mulyankan-migration.sql
test -s /tmp/mulyankan-migration.sql

npm run lint
npm run build
npm audit --audit-level=high

if command -v docker >/dev/null 2>&1; then
  docker compose config -q
else
  python scripts/quality/validate_compose.py
fi

release_dir="$(mktemp -d)"
trap 'rm -rf "$release_dir"' EXIT
python scripts/quality/create-release.py --source . --output-dir "$release_dir"
python scripts/quality/verify-release.py --release-dir "$release_dir"

echo "All Mulyankan release quality gates passed."
