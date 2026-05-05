# Metabase Droplet Deployment

Production deployment files for running Metabase on a standalone DigitalOcean
droplet. Metabase reads from the production analytics Postgres via a read-only
user and is served over HTTPS at `https://metabase.{domain}`.

This stack is decoupled from the main app (option 2 in #895) so analytics infra
can be restarted without affecting `mpi-backend`. The compose file is structured
to allow Airflow / Dagster to be added later as additional services.

> Related issues: #688 (POC), #895 (this deployment)

---

## Stack

| Service       | Image                       | Purpose                                                      |
| ------------- | --------------------------- | ------------------------------------------------------------ |
| `metabase`    | `metabase/metabase:v0.50.x` | Metabase server                                              |
| `metabase_db` | `postgres:16`               | Metabase's own application DB (questions/dashboards/users)   |
| `caddy`       | `caddy:2-alpine`            | TLS reverse proxy with auto Let's Encrypt certs              |

### What is Caddy and why are we using it?

Caddy is a small open-source web server (same category as Nginx / HAProxy /
Traefik). The reason we picked it for this stack is a single feature:

- **Automatic HTTPS.** Point a DNS A record at the droplet, list the domain in
  the `Caddyfile`, and Caddy itself talks to Let's Encrypt to fetch and
  auto-renew the TLS certificate. No certbot, no cron, no manual renewal.
- **Tiny config.** Our entire `Caddyfile` is ~30 lines for "terminate TLS,
  forward to Metabase, set security headers". The Nginx equivalent is ~100
  lines plus a separate certbot job.
- **Sensible defaults.** HTTP/2, gzip + zstd compression, HTTP→HTTPS
  redirect, modern TLS ciphers — all on by default.

Metabase listens on plain HTTP `:3000` inside Docker. Caddy publishes `:80`
and `:443` to the public internet, terminates TLS, and reverse-proxies to
`metabase:3000` over the internal Docker network. Browsers only ever talk to
Caddy.

The analytics Postgres connection (`mpi_db`) is added through the Metabase UI
on first login. It is **not** defined in compose so credentials never live on
disk in plain text.

---

## Production rollout flow (high level)

End-to-end deployment flow once this PR is merged:

| Step | What happens                                                                                                   |
| ---- | -------------------------------------------------------------------------------------------------------------- |
| 1    | Provision a 2 vCPU / 4 GB droplet on DigitalOcean. Open `22`, `80`, `443` only.                                |
| 2    | Add `metabase.{domain}` A record → droplet IP. Copy `.env.example` → `.env` and fill production values.        |
| 3    | `docker compose pull && docker compose up -d`. Three containers come up: `metabase_db`, `metabase`, `caddy`.   |
| 4    | Caddy auto-fetches the Let's Encrypt cert on first request to `:80`/`:443`; cached in the `caddy_data` volume. |
| 5    | First-login: create admin → add `mpi_db` data source pointing at production Postgres with the read-only user.  |
| 6    | Set `METABASE_SECRET_KEY` (= `MB_EMBEDDING_SECRET_KEY`) and `METABASE_SITE_URL` in the `mpi-backend` prod env.  |
| 7    | Recreate the 20+ POC saved questions / 5 dashboards against production data; verify the `/analytics` iframes.  |

Risk checkpoints (what could fail and where):

| Failure                                  | Where it surfaces             | Fix                                                                  |
| ---------------------------------------- | ----------------------------- | -------------------------------------------------------------------- |
| Cert issuance fails                      | Step 4, `docker compose logs caddy` | DNS not propagated, or ports `80/443` not reachable. Wait / firewall.|
| Metabase can't reach prod Postgres       | Step 5, "Test connection"     | Droplet IP not allowlisted on the prod DB, or VPC not joined.        |
| Embedded charts in `/analytics` are blank| Step 6, browser console       | `MB_EMBEDDING_SECRET_KEY` ≠ `METABASE_SECRET_KEY`, or origin missing.|

This PR ships **steps 1-3 in code form** (compose, Caddyfile, env template)
and provides the runbook for steps 4-7 in the
[Production deployment](#production-deployment) section below.

---

## Files

```text
deploy/metabase/
├── docker-compose.yml                  # Stack definition
├── docker-compose.override.yml.example # Local smoke-test overrides (gitignored when copied)
├── Caddyfile                           # Reverse proxy + TLS config
├── .env.example                        # Env template (copy to .env on the droplet)
└── README.md                           # This file
```

---

## Production deployment

### Prerequisites

1. **DigitalOcean droplet**
   - Recommended: 2 vCPU / 4 GB RAM / 80 GB SSD (s-2vcpu-4gb)
   - Ubuntu 22.04 LTS
   - Firewall: allow `22/tcp` (SSH), `80/tcp`, `443/tcp`. Block everything else.
   - Optional but recommended: place the droplet in the **same VPC** as the
     production Postgres so DB traffic stays on the private network.

2. **DNS**
   - `A` record for `metabase.{domain}` → droplet public IPv4.

3. **Read-only Postgres user** on the production analytics DB
   ```sql
   CREATE USER metabase_ro WITH PASSWORD '<strong-password>';
   GRANT CONNECT ON DATABASE mpi_db TO metabase_ro;
   GRANT USAGE ON SCHEMA analytics TO metabase_ro;
   GRANT SELECT ON ALL TABLES IN SCHEMA analytics TO metabase_ro;
   ALTER DEFAULT PRIVILEGES IN SCHEMA analytics
     GRANT SELECT ON TABLES TO metabase_ro;
   ```
   If the DB sits behind a firewall, allow inbound `5432/tcp` from the droplet IP
   (or the VPC CIDR if you set up a VPC).

### 1. Install Docker on the droplet

```bash
ssh root@<droplet-ip>

apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
usermod -aG docker $USER
```

### 2. Pull the deployment files

Clone the repo (or copy just `deploy/metabase/`):

```bash
mkdir -p /opt && cd /opt
git clone https://github.com/Mpi-plumbing/mpi-backend.git
cd mpi-backend/deploy/metabase
```

> Once CI/CD is wired up, this directory will be synced automatically on PR
> merges. Until then, `git pull` to update.

### 3. Configure secrets

```bash
cp .env.example .env
chmod 600 .env
vi .env
```

Fill in:

| Variable                   | Notes                                                                                |
| -------------------------- | ------------------------------------------------------------------------------------ |
| `METABASE_DOMAIN`          | e.g. `metabase.mpiplumbing.com`                                                      |
| `METABASE_SITE_URL`        | `https://` + `METABASE_DOMAIN`                                                       |
| `LETSENCRYPT_EMAIL`        | Address Let's Encrypt notifies on cert issues                                        |
| `MB_EMBEDDING_APP_ORIGIN`  | Frontend origin(s), e.g. `https://app.mpiplumbing.com`                               |
| `MB_EMBEDDING_SECRET_KEY`  | `openssl rand -hex 32` — **must match** `METABASE_SECRET_KEY` in `mpi-backend` `.env` |
| `METABASE_DB_PASSWORD`     | `openssl rand -base64 32`                                                            |

### 4. Bring the stack up

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f metabase
```

Caddy will fetch a Let's Encrypt cert on first boot — this takes ~30-60s and
requires ports 80/443 to be reachable from the public internet.

### 5. First-login setup in Metabase

1. Open `https://{METABASE_DOMAIN}` and create the admin account.
2. **Settings → Admin → Databases → Add database**
   - Type: PostgreSQL
   - Name: `mpi_db (production)`
   - Host: production Postgres host (private IP if using VPC)
   - Port: `5432`
   - DB name: `mpi_db`
   - Username / password: `metabase_ro` / read-only password
   - SSL: enable if the production DB requires it
3. Recreate the 20+ saved questions / 5 dashboards from the POC against the
   production data (Overview, Data Review, Mapping Coverage, Pricing, Full
   Dashboard tabs in `mpi-plumbing-fe/src/pages/analytics/Analytics.tsx`).
4. **Settings → Admin → Embedding**
   - Confirm "Embedding" is enabled.
   - Confirm `MB_EMBEDDING_APP_ORIGIN` value is reflected.
5. Invite team users via **Settings → Admin → People**.

### 6. Wire up `mpi-backend`

In the `mpi-backend` production environment set:

```env
METABASE_SITE_URL=https://metabase.{domain}
METABASE_SECRET_KEY=<same value as MB_EMBEDDING_SECRET_KEY on the droplet>
```

Then verify the embedded charts on the frontend `/analytics` page load.

---

## Run Metabase locally

Use this to spin up Metabase against your local `mpi_db` for development,
demos, or recreating saved questions / dashboards before production rollout.
Caddy + Let's Encrypt cannot issue real certs for `localhost`, so locally we
skip the proxy and expose Metabase directly on `http://localhost:3000`.

### Prerequisites

- Docker Desktop running.
- A local Postgres on `localhost:5432` with the `mpi_db` database, so
  Metabase has data to query. Skip whichever step doesn't apply to your
  setup:
  - **Docker users:** boot the `mpi_database` service from the repo root.
    Skip if it's already running:
    ```bash
    docker compose up -d mpi_database
    ```
  - **Native Postgres users:** make sure your local Postgres is running and
    listening on `localhost:5432` with the `mpi_db` database (e.g.
    `brew services start postgresql@16`, `pg_ctl start`, or your service
    manager of choice). No Docker needed for the database.

  Either way, Metabase reaches it from inside its container via
  `host.docker.internal:5432`.

### 1. Boot the stack

```bash
cd deploy/metabase

# Enable the localhost overrides (publishes Metabase on :3000, gitignored).
cp docker-compose.override.yml.example docker-compose.override.yml

# Boot just Metabase + its app DB (skip Caddy — no TLS on localhost).
# `.env.example` has safe local defaults; no edits required.
docker compose --env-file .env.example up -d metabase_db metabase

# Wait ~30-90s for migrations, then verify health:
curl -fsS http://localhost:3000/api/health    # expect {"status":"ok"}
```

#### Platform notes (Mac / Windows / Linux)

| Host                           | Image arch  | Boot time    | What you'll see / need to do                                           |
| ------------------------------ | ----------- | ------------ | ---------------------------------------------------------------------- |
| **Mac (Intel)**                | native amd64| ~20-30s      | Just works.                                                            |
| **Mac (Apple Silicon, M1/M2/…)**| amd64 emulated | ~40-60s   | One-line "platform does not match" warning on `up` — harmless.         |
| **Windows (x64)**              | native amd64| ~20-30s      | Use Docker Desktop with the WSL2 backend.                              |
| **Windows (ARM)**              | amd64 emulated | ~40-60s   | Same emulation warning as Apple Silicon.                               |
| **Linux**                      | native amd64| ~20-30s      | `host.docker.internal` doesn't exist by default — see note below.      |

Metabase publishes only `linux/amd64` images today, so any ARM host runs it
under Docker's transparent emulation layer. Functionally identical, just a
bit slower at boot.

> **Linux only:** to let the Metabase container reach Postgres on the host
> machine via `host.docker.internal`, add this to the `metabase` service in
> `docker-compose.override.yml`:
>
> ```yaml
> services:
>   metabase:
>     extra_hosts:
>       - "host.docker.internal:host-gateway"
> ```
>
> On Mac and Windows Docker Desktop adds this hostname automatically.

### 2. Create the admin account

Open <http://localhost:3000> and walk through the setup wizard:

| Field           | Value                                  |
| --------------- | -------------------------------------- |
| Language        | English                                |
| Name / email    | Anything (local only)                  |
| Password        | Anything (local only)                  |
| Company name    | e.g. `MPI (local)`                     |
| **Add data**    | Choose **I'll add my data later**      |

The "add data" step asks for a connection — skip it; we'll add `mpi_db` next
so we can name it cleanly.

### 3. Connect Metabase to the local `mpi_db`

**Settings (gear icon, top-right) → Admin settings → Databases → Add database**

| Field                | Value                                                                  |
| -------------------- | ---------------------------------------------------------------------- |
| Database type        | PostgreSQL                                                             |
| Display name         | `mpi_db (local)`                                                       |
| Host                 | `host.docker.internal`                                                 |
| Port                 | `5432`                                                                 |
| Database name        | `mpi_db`                                                               |
| Username             | `woodpecker`                                                           |
| Password             | `woodpecker`                                                           |
| Schemas              | Leave default (`All`) or restrict to `analytics,public`                |
| Use a secure SSL conn| **Off** (local Postgres has no TLS)                                    |

Click **Save**. Metabase will scan the schema (~10-30s) and you can browse
tables under **Browse data → mpi_db (local)**.

(Linux users: see the platform notes above for the `host.docker.internal`
override needed in `docker-compose.override.yml`.)

### 4. (Optional) Test the embed contract end-to-end

Embedded charts in `mpi-plumbing-fe`'s `/analytics` page require:

1. The same secret on both sides:
   ```bash
   # In deploy/metabase/.env (or whichever env file you booted with):
   MB_EMBEDDING_SECRET_KEY=<openssl rand -hex 32>

   # In the repo-root .env (used by mpi-backend):
   METABASE_SECRET_KEY=<same value>
   METABASE_SITE_URL=http://localhost:3000
   ```
2. In Metabase: open a question or dashboard → **... menu → Embed →
   Public embed → Enable**, copy its ID, and use it in the frontend.

### 5. Tear down

```bash
docker compose down       # stop, keep the Metabase app DB
docker compose down -v    # full reset (wipes saved questions/dashboards)
```

### Troubleshooting

| Symptom                                | Likely cause                                                                                          |
| -------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `curl :3000/api/health` returns 503    | Migrations still running — wait another 30-60s.                                                       |
| `:3000/api/health` never reaches 200   | `docker compose --env-file .env.example logs metabase` — usually a port conflict or DB auth mismatch. |
| Can't connect to `mpi_db` from the UI  | `main_database` container not running, or `host.docker.internal` not resolving (Linux — see note).   |
| `mpi_db` shows zero tables             | The `analytics` schema (dbt marts) hasn't been built yet — run dbt first.                             |
| "Platform does not match" warning      | Cosmetic — ARM hosts (Apple Silicon, ARM Windows) emulate the amd64 image. See platform notes above.   |

---

## Operations

### Update Metabase

```bash
cd /opt/mpi-backend
git pull
cd deploy/metabase
docker compose pull
docker compose up -d
```

The Metabase app DB (`metabase_pgdata` volume) is preserved across upgrades.

### Backups

The only stateful volume is `metabase_pgdata`. Back it up nightly with:

```bash
docker compose exec -T metabase_db \
  pg_dump -U "$METABASE_DB_USER" "$METABASE_DB_NAME" \
  | gzip > /opt/backups/metabase_$(date +%F).sql.gz
```

Schedule via cron / systemd timer and ship to S3 or DO Spaces.

### Logs

```bash
docker compose logs -f metabase
docker compose logs -f caddy
```

### Restart / stop

```bash
docker compose restart metabase
docker compose down            # stop everything (volumes preserved)
docker compose down -v         # WIPES the Metabase app DB — only for resets
```

---

## Adding Airflow / Dagster later

Append a new service block to `docker-compose.yml`, attach it to
`internal_ntw`, and add a route in the `Caddyfile` if it needs a public URL
(e.g. `airflow.{domain}`). Keep their app DBs as separate Postgres services
or schemas so each tool can be upgraded independently.

---

## Security notes

- `.env` lives on the droplet only and is `chmod 600`. Never commit it.
- The Metabase app DB (`metabase_db`) is **not** published on a host port; it
  is only reachable on the internal Docker network.
- `MB_EMBEDDING_SECRET_KEY` must match `METABASE_SECRET_KEY` in `mpi-backend`.
  Rotating it requires updating both sides simultaneously.
- The analytics DB user **must** be read-only. Metabase native queries can
  execute arbitrary SQL — a writable user is a foot-gun.
