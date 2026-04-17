# Shadow Pages — Railway Deployment Guide

## Architecture on Railway

Railway deploys the project via Docker Compose (`docker-compose.yml` at repo root).
Each compose service becomes a separate Railway service with internal networking.

| Service            | Image / Build            | Notes                                          |
|--------------------|--------------------------|------------------------------------------------|
| **postgres**       | `postgres:16-alpine`     | Persistent volume, healthcheck enabled         |
| **redis**          | `redis:7-alpine`         | AOF persistence, 256 MB memory limit           |
| **minio**          | `minio/minio:latest`     | S3-compatible object storage, persistent volume |
| **minio-init**     | `minio/mc:latest`        | One-shot: creates buckets then exits           |
| **api**            | `services/api/Dockerfile`| FastAPI, 2 uvicorn workers                     |
| **worker-scraper** | `services/worker/Dockerfile` | Celery: scrape, discover, analyze (c=4)   |
| **worker-downloader** | `services/worker/Dockerfile` | Celery: download, search (c=4)         |
| **worker-enhancer**| `services/worker/Dockerfile` | Celery: enhance, export (c=2)            |
| **celery-beat**    | `services/worker/Dockerfile` | Celery beat scheduler                    |
| **web**            | `apps/web/Dockerfile`    | Next.js 14 standalone                          |
| **nginx**          | `infra/nginx/Dockerfile.railway` | Reverse proxy, public entry point      |

---

## Prerequisites

1. A Railway account at <https://railway.app>
2. The Railway CLI installed: `npm i -g @railway/cli`
3. Your repo pushed to GitHub (Railway deploys from a connected repo)

---

## Step-by-step deployment

### 1. Create a new Railway project

```bash
railway login
railway init
```

Or create a project from the Railway dashboard and link it:

```bash
railway link
```

### 2. Set environment variables

In the Railway dashboard, go to your project and set these **shared variables** (available to all services):

| Variable              | Example value                   | Required |
|-----------------------|---------------------------------|----------|
| `DB_USER`             | `vre_user`                      | Yes      |
| `DB_PASSWORD`         | *(generate a strong password)*  | Yes      |
| `POSTGRES_DB`         | `vre`                           | Yes      |
| `MINIO_ACCESS_KEY`    | *(generate)*                    | Yes      |
| `MINIO_SECRET_KEY`    | *(generate)*                    | Yes      |
| `JWT_SECRET`          | *(generate, 64+ chars)*         | Yes      |
| `RAPIDAPI_KEY`        | *(your RapidAPI key)*           | Yes      |
| `AI_PROVIDER`         | `anthropic`                     | No       |
| `ANTHROPIC_API_KEY`   | *(your key)*                    | No       |
| `CORS_ORIGINS`        | `*`                             | No       |
| `RESEND_API_KEY`      | *(your key)*                    | No       |
| `EMAIL_FROM`          | `noreply@yourdomain.com`        | No       |

**After first deploy**, once Railway assigns a public URL to the nginx service, set:

| Variable              | Example value                          |
|-----------------------|----------------------------------------|
| `APP_URL`             | `https://nginx-production-xxxx.up.railway.app` |

Then redeploy so the web service bakes in the correct API URL.

### 3. Deploy

Push to your connected branch. Railway auto-detects `docker-compose.yml` and creates all services.

Or deploy manually:

```bash
railway up
```

### 4. Expose the nginx service publicly

In the Railway dashboard:
1. Click on the **nginx** service
2. Go to **Settings** > **Networking**
3. Click **Generate Domain** to get a public `*.up.railway.app` URL
4. (Optional) Add a custom domain and point your DNS to Railway

Railway handles SSL/TLS automatically for all public domains.

### 5. Update APP_URL and redeploy

Once you have the public nginx URL:

1. Set `APP_URL` to the full URL (e.g., `https://shadow-pages.up.railway.app`)
2. Redeploy the **web** service so Next.js bakes in the correct API endpoint

---

## Custom domain setup

1. In Railway dashboard, click **nginx** > **Settings** > **Custom Domain**
2. Add your domain (e.g., `app.shadowpages.io`)
3. Create a CNAME record pointing to the Railway-provided target
4. Railway provisions a TLS certificate automatically

---

## Database migrations

Run migrations against the Railway PostgreSQL instance:

```bash
# Get the DATABASE_URL from Railway
railway variables

# Or run a one-off command inside the api service
railway run --service api -- python -c "from db.init import init_db; import asyncio; asyncio.run(init_db())"
```

---

## Scaling

Railway lets you scale each service independently:

- **Workers**: Increase concurrency via the command (e.g., change `-c 4` to `-c 8`)
- **API**: Increase `--workers` in the api command
- **Horizontal**: Railway supports multiple replicas per service in Pro plans

To adjust worker concurrency, edit `docker-compose.yml` and push.

---

## Monitoring

- **Railway dashboard**: CPU, memory, network metrics per service
- **Logs**: `railway logs --service <service-name>`
- **API health**: `GET /health` on the nginx public URL
- **Celery tasks**: Add Flower as a service if needed (not included by default to save resources)

### Adding Flower (optional)

Add this to `docker-compose.yml`:

```yaml
flower:
  build:
    context: ./services/worker
    dockerfile: Dockerfile
  environment:
    REDIS_URL: redis://redis:6379/0
  command: ["celery", "-A", "celery_app", "flower", "--port=5555", "--url_prefix=flower"]
  depends_on:
    redis:
      condition: service_healthy
```

---

## Cost estimates (Railway)

| Service          | Recommended plan | Approx. cost/month |
|------------------|-----------------|---------------------|
| postgres         | 1 GB RAM        | ~$5                 |
| redis            | 256 MB RAM      | ~$3                 |
| minio            | 512 MB RAM      | ~$3                 |
| api              | 512 MB RAM      | ~$5                 |
| worker-scraper   | 1 GB RAM        | ~$7                 |
| worker-downloader| 1 GB RAM        | ~$7                 |
| worker-enhancer  | 1 GB RAM        | ~$7                 |
| celery-beat      | 256 MB RAM      | ~$2                 |
| web              | 512 MB RAM      | ~$5                 |
| nginx            | 256 MB RAM      | ~$2                 |
| **Total**        |                 | **~$46/month**      |

Railway bills per usage (CPU + memory + network). Actual costs depend on traffic.

---

## Troubleshooting

**Services can't connect to each other**
- Railway Docker Compose uses service names as hostnames (e.g., `postgres`, `redis`, `minio`)
- Verify env vars reference the correct service names

**Next.js shows wrong API URL**
- `NEXT_PUBLIC_API_URL` is baked in at build time
- After changing `APP_URL`, you must redeploy the **web** service

**MinIO buckets not created**
- Check `minio-init` service logs: `railway logs --service minio-init`
- The service runs once and exits; Railway may show it as "crashed" which is normal

**Worker OOM (out of memory)**
- Reduce concurrency (`-c 2` instead of `-c 4`)
- Increase RAM allocation in Railway dashboard

**Database connection refused**
- Ensure postgres healthcheck passes before api/workers start
- Check `DB_PASSWORD` is set and matches across services
