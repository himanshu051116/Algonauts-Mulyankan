"""pytest configuration for backend tests."""

import os

# Force test settings — no DB, no external services
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["JWT_SECRET"] = "test-secret-not-for-production"
os.environ["REDIS_URL"] = "redis://127.0.0.1:6379/0"
os.environ["STORAGE_ENDPOINT"] = "http://localhost:9000"
os.environ["CORS_ORIGINS"] = "http://localhost:5173"
os.environ["ALLOWED_EXTENSIONS"] = ".pdf,.docx,.txt"
os.environ["METRICS_ENABLED"] = "false"

pytest_plugins = []
