# Free demo deployment

This option deploys the API and queue worker together on one free Render web
service. It is suitable for a hackathon demonstration with synthetic or
non-sensitive pilot data. It is not a production deployment: Render can sleep
the service after inactivity, restart it without notice, and limit monthly
runtime. A queued job waits until the service wakes again.

The deployment uses the following free services:

- Render web service for the API and co-located ARQ worker.
- Supabase for PostgreSQL, Auth, and private S3-compatible Storage.
- Upstash Redis for the persistent job queue.

Do not submit sensitive coal-proposal documents to this free environment.

## Create the supporting services

1. Create a Supabase Free project. In **Authentication**, configure the Vercel
   site URL and the exact `/auth/callback` and `/auth/reset-password` redirect
   URLs. Use an asymmetric JWT signing key supported by the backend (RS256 or
   ES256).
2. In **Storage > Configuration > S3**, enable the S3 protocol, generate a
   server-only access-key pair, and create a **private** bucket named
   `mulyankan-proposals`. Keep its access key and secret out of source control.
3. In **Connect**, copy the **Session pooler** database connection string.
   Replace its `postgresql://` prefix with `postgresql+asyncpg://` before
   supplying it to Render. The session pooler is required because Free
   Supabase direct connections are IPv6-only.
4. Create an Upstash Redis Free database and copy its TLS (`rediss://`)
   connection URL. The application supports this secure URL format.

## Deploy on Render

1. In Render, select **New > Blueprint** and choose this GitHub repository.
   Render reads the committed `render.yaml` and selects its Free plan.
2. During the first setup, Render prompts for the secrets marked as private:
   `DATABASE_URL`, `REDIS_URL`, `SUPABASE_URL`, `STORAGE_ENDPOINT`,
   `STORAGE_PUBLIC_ENDPOINT`, `STORAGE_ACCESS_KEY`, `STORAGE_SECRET_KEY`, and
   `STORAGE_REGION`.
3. For both storage endpoint variables, use the S3 endpoint shown in Supabase
   Storage, for example
   `https://<project-ref>.storage.supabase.co/storage/v1/s3`. Use the region
   shown beside it in the Supabase dashboard.
4. Wait for the first deploy, then open `/health/ready`. It must return
   `"status":"ready"`; it also confirms the database migration, reference
   data, private bucket, Redis connection, and worker heartbeat.
5. Copy the resulting `https://…onrender.com` API URL into the Vercel
   production variable `VITE_API_URL`, redeploy Vercel, and test sign-in plus
   one small benign upload.

## Free-plan limits

- A free Render web service spins down after 15 minutes with no inbound
  traffic and may take about a minute to wake. It has an ephemeral filesystem
  and can restart at any time.
- The free runner intentionally has `ENVIRONMENT=demo`, disables malware
  scanning and metrics, and starts the worker in the same process as the API.
  These constraints keep the deployment honest: it must not be represented as
  a production or continuously reliable service.
- Upstash Free has usage and inactivity limits; Supabase Free also has service
  limits. Monitor their dashboards before a demo.
- The paid architecture should instead run a separate worker, persistent
  Redis, scheduled malware-signature updates, monitoring, backups, and a
  production environment gate.
