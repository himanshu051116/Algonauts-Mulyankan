# Mulyankan — Local Windows Runtime Guide

## Overview

Mulyankan runs entirely on your Windows machine using Docker containers. All services
(PostgreSQL, Redis, MinIO, backend API, ARQ worker, frontend) are packaged in containers
and orchestrated with Docker Compose.

The application is designed to be **permanently available at `http://localhost:3000`**
when your computer is running and Docker Desktop is active.

---

## Architecture

```
Windows Desktop
  │
  ├── http://localhost:3000  →  Nginx (frontend container)
  │     │
  │     ├── /api/*           →  FastAPI backend (container)
  │     ├── /health          →  FastAPI health
  │     ├── /docs            →  Swagger UI
  │     └── /*               →  Vite SPA (index.html)
  │
  ├── http://localhost:9000  →  MinIO API (direct browser uploads)
  ├── http://localhost:9001  →  MinIO Console
  └── http://localhost:5432  →  PostgreSQL (internal only)
```

### Services

| Service    | Compose service | Image                     | Port(s)        | Persistence  |
|------------|-----------------|---------------------------|----------------|--------------|
| frontend   | `frontend`      | nginx + Vite build        | 127.0.0.1:3000 | —            |
| backend    | `backend`       | local backend image       | — (internal)   | —            |
| worker     | `worker`        | local backend image       | — (internal)   | —            |
| postgres   | `postgres`      | postgres:16-alpine        | 127.0.0.1:5432 | named volume |
| redis      | `redis`         | redis:7-alpine            | 127.0.0.1:6379 | named volume |
| minio      | `minio`         | minio/minio:latest        | 127.0.0.1:9000 | named volume |

### Volumes

| Compose volume    | Data stored                                      |
|-------------------|--------------------------------------------------|
| `postgres_data`   | All database records (users, proposals, reviews) |
| `minio_data`      | Uploaded proposal documents                      |
| `redis_data`      | Redis AOF persistence (job queue state)          |

Docker Compose prefixes the actual volume names with the Compose project name, which normally comes from the checkout directory. All three volumes are **named** and persist across container restarts and Compose stop/start cycles.
Data is **destroyed only** when `docker compose down -v` is run explicitly.

---

## One-Time Installation

### Prerequisites

1. **Docker Desktop** for Windows (>= 4.30)
   - Download: https://docs.docker.com/desktop/setup/install/windows-install/
   - WSL 2 backend recommended
   - Enable: Settings → General → "Start Docker Desktop when you sign in"

2. **PowerShell 5.1+** (comes with Windows)

### Steps

1. Clone or copy the repository to your Windows machine.
2. Open a terminal in the repository root (the folder containing `docker-compose.yml`).
3. Create a `.env` file by copying `.env.example`:

   ```
   copy .env.example .env
   ```

4. Edit `.env` with your local values:

   - `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` — local PostgreSQL credentials
   - `MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD` — local MinIO credentials
   - `JWT_SECRET` — a long random string (minimum 32 characters)
   - `VITE_SUPABASE_URL` — your Supabase project URL (or `http://localhost` if not using)
   - `VITE_SUPABASE_PUBLISHABLE_KEY` — your Supabase anonymous key
   - `AUTH_ALLOW_LOCAL_JWT=true` — enables local JWT for development

5. Install the Windows auto-start:

   ```
   .\scripts\windows\install-autostart.ps1 -DesktopShortcut
   ```

   This creates:
   - A **Windows Scheduled Task** named `Mulyankan Auto Start` that runs at logon.
   - An optional **desktop shortcut** to open Mulyankan.

6. For Docker Desktop auto-start:
   - Open Docker Desktop → Settings → General
   - Check "Start Docker Desktop when you sign in"

---

## Daily Use

### Normal startup

On Windows logon, Docker Desktop starts automatically (if configured).
The Scheduled Task waits 1 minute, then starts the Mulyankan stack.

**Double-click the "Mulyankan" desktop shortcut**, or run:

```
.\scripts\windows\open-mulyankan.ps1
```

This opens `http://localhost:3000`. If the stack is not running, it starts it first.

### Manual commands

| Action                      | Command                                             |
|-----------------------------|-----------------------------------------------------|
| Start the stack             | `.\scripts\windows\start-mulyankan.ps1`             |
| Start and open browser      | `.\scripts\windows\start-mulyankan.ps1 -OpenBrowser`|
| Open application            | `.\scripts\windows\open-mulyankan.ps1`              |
| Stop the stack              | `.\scripts\windows\stop-mulyankan.ps1`              |
| Restart the stack           | `.\scripts\windows\restart-mulyankan.ps1`           |
| Check status                | `.\scripts\windows\status-mulyankan.ps1`            |
| Update after code changes   | `.\scripts\windows\update-mulyankan.ps1`            |
| Rebuild and start           | `.\scripts\windows\start-mulyankan.ps1 -Build`     |

### Production mode (from repository root)

```
docker compose up -d
```

The stack starts in production mode — frontend served through Nginx, backend internal.
All services restart automatically unless stopped.

### Development mode (from repository root)

```
docker compose -f docker-compose.yml -f compose.dev.yml up
```

This adds:
- **Backend**: source-code bind mount + `--reload` for hot-reload
- **Backend**: exposed on `http://localhost:8000`
- **Worker**: source-code bind mount

---

## Data Persistence

### What survives restarts

- All PostgreSQL data: users, proposals, versions, reviews, audit events
- All MinIO objects: uploaded proposal documents
- All Redis data: job queue state (with AOF persistence)

### What is temporary

- Backend process state (recreated on restart)
- Worker process state (recreated on restart)
- ARQ job queue in memory (lost if Redis is not cleanly shut down)

### Backup

To back up PostgreSQL:

```
docker compose exec postgres pg_dump -U $POSTGRES_USER $POSTGRES_DB > mulyankan-backup-$(date +%F).sql
```

To back up MinIO objects:

```
docker compose exec minio mc mirror local/mulyankan-proposals /backup/
```

### Data safety rules

- **Never** run `docker compose down -v` unless you intend to destroy all data.
- **Never** run `docker volume rm` with a Mulyankan volume name.
- Use `docker compose stop` (not `down`) to pause the stack.
- Use `.\scripts\windows\stop-mulyankan.ps1` to stop safely.

---

## Troubleshooting

### Docker Desktop not starting

Check Docker Desktop → Troubleshoot → Restart / Reset to factory defaults.
Ensure WSL 2 is installed: `wsl --set-default-version 2`

### Port 3000 already in use

Find the process:
```
netstat -ano | findstr :3000
```

Stop the conflicting process or change the frontend port in `docker-compose.yml`.

### Backend unhealthy

Check logs:
```
docker compose logs backend
```

Common causes:
- PostgreSQL not ready yet (wait for health check)
- Missing environment variables in `.env`
- Database connection refused (wrong credentials)

### PostgreSQL unhealthy

```
docker compose logs postgres
```

Common causes:
- Volume corruption (rare — restore from backup)
- Port conflict on 5432

### Redis unhealthy

```
docker compose logs redis
```

### MinIO unhealthy

```
docker compose logs minio
```

### Browser upload fails (CORS)

Ensure the MinIO CORS policy allows `http://localhost:3000`.
Run the init script:
```
.\scripts\windows\init-minio-cors.ps1
```

### Supabase redirect problems

Ensure your Supabase project allows the redirect URL:
```
http://localhost:3000/auth/callback
```

### Stale Docker images

Remove old images periodically:
```
docker image prune -a --filter "until=24h"
```

### Scheduled task quoting failures

If the scheduled task fails with path errors, reinstall it:
```
.\scripts\windows\uninstall-autostart.ps1
.\scripts\windows\install-autostart.ps1 -DesktopShortcut
```

---

## Maintenance

### Rebuilding after code changes

```
.\scripts\windows\update-mulyankan.ps1
```

Or manually:
```
docker compose build frontend backend worker
docker compose up -d --remove-orphans
```

### Reinstalling auto-start after moving the project

1. Run uninstall:
   ```
   .\scripts\windows\uninstall-autostart.ps1 -RemoveShortcut
   ```
2. Move the project folder to the new location.
3. Run install from the new location:
   ```
   .\scripts\windows\install-autostart.ps1 -DesktopShortcut
   ```

### Removing auto-start (without deleting the application)

```
.\scripts\windows\uninstall-autostart.ps1
```

This removes only the Scheduled Task. Containers, volumes, and data are preserved.

---

## Demonstration Day Checklist

1. Reboot Windows.
2. Sign in.
3. Wait 2 minutes for Docker Desktop and Scheduled Task.
4. Double-click the Mulyankan desktop shortcut.
5. Confirm `http://localhost:3000` opens.
6. Confirm login page renders.
7. Confirm existing proposals and files are present (if any).
8. Confirm all services healthy: `.\scripts\windows\status-mulyankan.ps1`

### Quick smoke test

```powershell
.\scripts\windows\status-mulyankan.ps1
```

Expected output: all services "healthy" or "up", both HTTP endpoints green.

---

## Security Notes

- All services bind to `127.0.0.1` only — not accessible from other machines on the network.
- MinIO uses signed URLs and private buckets — no anonymous public access.
- Supabase JWT verification is enforced on all authenticated endpoints.
- The `.env` file is never copied into Docker images.
- Backend secrets (JWT_SECRET, MINIO_ROOT_PASSWORD, POSTGRES_PASSWORD) are
  never embedded in the frontend image.
- The frontend image only contains publicly visible Supabase credentials.

**Do not expose `localhost:3000` to the public internet.**
This application is designed for local or private-network use only.

---

## Commands Reference

```powershell
# Start (with health check wait)
docker compose up -d --remove-orphans

# Start development mode
docker compose -f docker-compose.yml -f compose.dev.yml up

# Stop (preserve containers + data)
docker compose stop

# Restart
docker compose restart

# View logs
docker compose logs -f <service>

# Rebuild a specific service
docker compose build frontend

# Full update
docker compose build frontend backend worker
docker compose up -d --remove-orphans

# List running services
docker compose ps

# List volumes
docker volume ls | findstr mulyankan

# Inspect volume location
docker compose exec postgres sh -lc 'echo "PostgreSQL volume is mounted at /var/lib/postgresql/data"'
```
