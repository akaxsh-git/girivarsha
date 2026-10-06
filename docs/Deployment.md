# Deployment (free tier: Neon + Render)

This puts Girivarsha on the public internet at no cost: a managed Postgres/PostGIS database on **Neon**, the FastAPI backend and the React frontend on **Render**. Config lives in `render.yaml` and `deploy/Dockerfile.backend`.

**What runs publicly:** the dashboards, risk engine (live Open-Meteo / NASA POWER inputs), evacuation routing, replay, what-if simulator. Sensors show the real Open-Meteo regional estimate (clearly labelled) because no MQTT broker, bridge or simulator is hosted.

**What does not:** the sensor simulator pipeline (it stays a local development tool).

## 1. Create the database on Neon

1. Sign up at neon.tech and create a project. Pick the **Singapore** region (same as the backend in `render.yaml`).
2. In the Neon **SQL Editor**, run: `CREATE EXTENSION IF NOT EXISTS postgis;`
3. Copy the connection string from the dashboard (Connection details, direct, not pooled). Rewrite its start for SQLAlchemy and make sure it ends with `?sslmode=require`:
   `postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require`
   (Neon shows `postgresql://...`; add `+psycopg` after `postgresql`.)

## 2. Create the tables and load the real data (from your own machine)

Render's free plan has no shell and no pre-deploy command, so you run migrations and seeds once from your laptop against Neon.

**First, protect your local sensor keys.** `seed_iot_nodes.py` merges new keys into `iot/device_keys.json`, which would overwrite the keys your local database expects. Back it up outside the repo and restore it afterwards:

```
cd ~/Downloads/girivarsha-phase11-regions
cp iot/device_keys.json ~/device_keys.local.backup.json
```

Then, in `backend/`:

```
cd backend && source .venv/bin/activate
export GIRIVARSHA_DATABASE_URL='postgresql+psycopg://USER:PASSWORD@HOST/DBNAME?sslmode=require'
alembic upgrade head
python ../scripts/seed_pilot_region.py
python ../scripts/seed_chamoli_valley.py
python ../scripts/seed_regions.py
python ../scripts/seed_event_timelines.py
python ../scripts/seed_iot_nodes.py
```

Restore your local keys and clear the variable:

```
cp ~/device_keys.local.backup.json ../iot/device_keys.json
unset GIRIVARSHA_DATABASE_URL
```

The keys generated for Neon are not needed: the hosted site has no publisher, and keyed sensors reject anonymous `POST /sensor-reading` requests, which is what you want on a public API.

## 3. Deploy on Render

1. Commit and push `render.yaml`, `deploy/`, `.dockerignore` and this file to GitHub.
2. Sign in at render.com with GitHub. **New, Blueprint**, pick the `girivarsha` repo. Render reads `render.yaml` and proposes two services.
3. When prompted, paste your Neon string as `GIRIVARSHA_DATABASE_URL`. Apply.
4. Wait for both to build (backend ~5 min, frontend ~2 min).

**If the service names are taken:** Render adds a suffix to the URL. Then update, in `render.yaml` or the Render dashboard: the frontend's `VITE_API_BASE_URL` to the real backend URL, the backend's `GIRIVARSHA_CORS_ORIGINS` to the real frontend URL (a JSON list, exactly matching, no trailing slash), then redeploy both.

## 4. Check it

- `https://girivarsha-api.onrender.com/api/v1/health` returns JSON.
- `https://girivarsha.onrender.com` loads the dashboard; `/authority` loads the authority view.
- A CORS error in the browser console means the two URLs in step 3 don't match.

## Things to know on the free tier

- **Cold starts.** The backend sleeps after 15 minutes idle and takes roughly 30-60 seconds to wake. The first visit after idle is slow; the site then behaves normally. A free uptime pinger (e.g. UptimeRobot hitting `/api/v1/health` every 10 minutes) keeps it awake.
- **Memory.** Render's free instance has 512MB. The road/trail network graph (71K nodes) is held in memory when evacuation routes are requested. If the service restarts with out-of-memory messages in its logs, move the backend to a paid instance (about $7/month) or another host.
- **Neon** suspends idle databases and wakes on the next query (about a second). Free-tier storage limits are far above this project's size.
- **Phone numbers.** `POST /notifications/subscribe` stores whatever a visitor enters. With the default `log_only` provider nothing is sent, but a public deployment would be collecting phone numbers, so consider removing or gating that form before promoting the site widely.
- **Writes on GET.** `GET /risk/*` opens, escalates and resolves alerts in the database (the real alert engine). That is by design, but it means anonymous page loads change data.
- **No MQTT/TLS hardening needed here**, since the hosted deployment has no broker. The gaps listed in `docs/Limitations.md` for a hosted sensor pipeline still apply if you add one later.

## Gotcha: database URL driver prefix

The backend uses SQLAlchemy with the `psycopg` v3 driver, so `GIRIVARSHA_DATABASE_URL` must start with `postgresql+psycopg://`. Neon shows `postgresql://...`; pasting that as-is makes SQLAlchemy look for `psycopg2` and every DB endpoint returns 500 (`No module named 'psycopg2'`) while `/health` still looks fine. Add `+psycopg` after `postgresql`, and never paste the real password into chat or commit it.

## Option: backend on your own free VM (fixes Open-Meteo 429s)

Render's free tier shares outbound IPs between many apps, so Open-Meteo's per-IP free quota (10,000 calls/day) is used up by others and every server-side weather call gets HTTP 429 — rainfall/soil silently fall back to simulated. A VM with its own public IP gets its own quota. Files: `deploy/vm/` (docker-compose with the API + Caddy for automatic HTTPS, `setup.sh`, `.env.example`).

1. Create an Ubuntu VM (e.g. Oracle Cloud Always Free, `VM.Standard.E2.1.Micro` or Ampere A1). Allow inbound TCP 80 and 443 in its cloud firewall / security list.
2. SSH in, `git clone` the repo, run `bash deploy/vm/setup.sh`, log out and back in.
3. `cp deploy/vm/.env.example deploy/vm/.env` and fill it in. `API_DOMAIN` is the VM's IP with dashes + `.sslip.io` (free DNS, e.g. `203-0-113-7.sslip.io`).
4. `docker compose -f deploy/vm/docker-compose.yml up -d --build`, then check `https://<API_DOMAIN>/api/v1/health`.
5. In Render, set the static site's `VITE_API_BASE_URL` to `https://<API_DOMAIN>` and redeploy it. The Render API service can then be suspended.

Updating later: `git pull && docker compose -f deploy/vm/docker-compose.yml up -d --build`.

## Hourly weather snapshot (GitHub Actions) — the no-card fix for Open-Meteo 429s

`.github/workflows/weather-snapshot.yml` runs `scripts/fetch_weather_snapshot.py` every hour (and on demand via "Run workflow"). It makes ONE batched Open-Meteo request for every village's current rainfall and soil moisture and upserts them into the `weather_snapshots` table (migration `8a1e4c2d9f10`). `RealRainfallProvider`/`RealSoilMoistureProvider` use a stored reading within ~5 km that is under 2 hours old before trying a live call, so the risk engine and the sensor "regional est." fallback get real data even when the host's shared IP is rate-limited. Risk component descriptions say "Open-Meteo hourly snapshot, N min old" so the age is always visible. If the job stops running, readings age out after 2 hours and the app degrades exactly as before (live call, then honest simulated fallback).

Setup:
1. Apply the migration to Neon from your laptop: `cd backend && GIRIVARSHA_DATABASE_URL='postgresql+psycopg://...' alembic upgrade head`.
2. GitHub repo → Settings → Secrets and variables → Actions → New repository secret: name `GIRIVARSHA_DATABASE_URL`, value = the same Neon URL.
3. Actions tab → "Hourly weather snapshot" → Run workflow, and check it goes green.

Cost: ~1 min per run, ~730 min/month, inside the free 2,000 min for private repos. Scheduled runs can start several minutes late.
