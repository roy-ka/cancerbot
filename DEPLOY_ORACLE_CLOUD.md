# CancerBot Deployment Guide - Oracle Cloud Ubuntu

This guide covers deploying CancerBot to an Oracle Cloud Ubuntu instance with Docker, including setup for persistent iptables rules to maintain Docker-host connectivity.

## Prerequisites

- Oracle Cloud Ubuntu instance (20.04 LTS or later)
- Docker and Docker Compose installed
- Python 3.12+
- Git
- 4GB+ RAM, 20GB+ disk space

## Initial Server Setup

### 1. Clone the repository

```bash
git clone https://github.com/roy-ka/cancerbot.git
cd cancerbot
```

### 2. Configure environment variables

```bash
cp example.env .env
# Edit .env with your values
nano .env
```

Required in production:
- `ENV=production`
- `FRONTEND_URL` — your public origin, e.g. `https://your-domain.com` (the backend refuses to start without it)
- `CORS_ORIGINS` — the same origin
- `JWT_SECRET`, `POSTGRES_PASSWORD`, `OPENSEARCH_INITIAL_ADMIN_PASSWORD`, `REDIS_PASSWORD`
- `LLM_PROVIDER=groq` and `GROQ_API_KEY`, `BREVO_API_KEY`
- `ADMIN_DIGEST_EMAILS` — where admin digests go

Don't set `POSTGRES_URL`, `OPENSEARCH_URL`, `OLLAMA_URL`, `NLP_SERVICE_URL` or `REDIS_URL` for production — `docker-compose.yml` and `docker-compose.prod.yml` set the in-network values for the backend and worker containers.

### 3. Install Ollama on host

Ollama runs on the host (not in Docker) and is used for embeddings only:

```bash
# On Ubuntu, follow: https://github.com/ollama/ollama/blob/main/README.md
curl -fsSL https://ollama.com/install.sh | sh
ollama pull nomic-embed-text
```

Containers reach Ollama through the Docker bridge gateway (`172.30.0.1`, set in `docker-compose.yml`), but the installer binds it to `127.0.0.1` only. Make it listen on all interfaces (keep port 11434 closed in your cloud firewall):

```bash
sudo systemctl edit ollama
# add:
#   [Service]
#   Environment="OLLAMA_HOST=0.0.0.0"
sudo systemctl restart ollama
sudo systemctl enable ollama
curl http://localhost:11434/api/tags
```

## Docker Deployment

Deploy with the deploy script — it builds the images and the frontend, starts the `prod` profile (backend, worker, Redis alongside the default services), waits for PostgreSQL and OpenSearch, runs migrations and seeds, and health-checks the result:

```bash
./scripts/deploy.sh
```

Then check:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot --profile prod ps
curl -i http://localhost:8000/health/
# 200 {"status":"ok","checks":{"database":{"status":"ok"},"ollama":{"status":"ok","models":1}},...}
# 503 with "status":"degraded" if PostgreSQL or Ollama is unreachable
```

## Docker-to-Host Connectivity (Iptables Fix)

### The Problem

When Docker restarts, it recreates network bridges and iptables rules are lost, breaking connectivity between Docker containers and the host (where Ollama runs). This causes the health check to fail and chat to fail with "Ollama unavailable" errors.

### The Solution

A systemd service automatically applies and persists iptables rules after Docker restarts.

### Setup (One-time, requires sudo)

```bash
# Make scripts executable
chmod +x scripts/fix-iptables.sh scripts/setup-iptables-service.sh

# Run setup as root (this creates and enables the systemd service)
sudo ./scripts/setup-iptables-service.sh
```

What this does:
1. Creates `/etc/systemd/system/iptables-docker.service` systemd unit
2. Enables the service to run on every boot after Docker starts
3. Immediately applies iptables rules so containers can reach the host
4. Saves rules persistently with netfilter-persistent

### Verify the service

```bash
# Check service status
sudo systemctl status iptables-docker.service

# View service logs
sudo journalctl -u iptables-docker.service -n 20

# Manually re-apply rules if needed
sudo ./scripts/fix-iptables.sh
```

### What the scripts do

**fix-iptables.sh:**
- Adds `iptables -I INPUT -i docker0 -j ACCEPT` (allow docker0 bridge)
- Adds `iptables -I INPUT -i br-<osnet> -j ACCEPT` (allow OpenSearch network)
- Saves rules with `netfilter-persistent save` for persistence across reboots

**setup-iptables-service.sh:**
- Creates systemd service that runs fix-iptables.sh after Docker starts
- Enables service for auto-run on every boot
- Starts the service immediately

## Using the Deploy Script

After the initial setup, use the deploy script for subsequent deployments:

```bash
# Interactive deploy (asks for confirmation)
./scripts/deploy.sh

# Automated deploy (skips confirmation)
./scripts/deploy.sh --force
```

The deploy script:
- Pulls latest code from git
- Creates PostgreSQL backup
- Builds Docker images
- Runs Alembic migrations
- Restarts services with `--force-recreate`
- Verifies health checks (30 retries × 5 seconds)
- Auto-rollback on failure with database restore

Deploy logs are saved to `logs/deploy_TIMESTAMP.log`

## Nginx Reverse Proxy Setup

nginx serves the built frontend (`client/dist`) and proxies the API path prefixes (`/auth/`, `/conversations/`, `/health/`, …) to the backend on port 8000. The configuration is the repository's `nginx.conf`, which `deploy.sh` copies to `/etc/nginx/sites-available/cancerbot` and reloads on every deploy — so edit the repository copy, never the installed one. Before the first deploy, edit it for your host:

- `root` — `<your checkout>/client/dist`
- `ssl_certificate` / `ssl_certificate_key` — your domain's Let's Encrypt paths

```bash
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo certbot certonly --nginx -d your-domain.com -d www.your-domain.com
sudo ln -s /etc/nginx/sites-available/cancerbot /etc/nginx/sites-enabled/
```

## Database Backups

Backups are created automatically before each deploy. Manual backup:

```bash
docker exec cancerbot-postgres pg_dump -U cancerbot cancerbot > backups/backup_manual_$(date +%Y%m%d_%H%M%S).sql
```

Restore from backup:
```bash
cat backups/backup_TIMESTAMP.sql | docker exec -i cancerbot-postgres psql -U cancerbot cancerbot
```

## Monitoring

### View logs

```bash
# Backend logs
docker logs cancerbot-backend-1 --follow

# OpenSearch logs
docker logs opensearch-node1 --follow

# PostgreSQL logs
docker logs cancerbot-postgres --follow
```

### Check container status

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot stats
```

### Health endpoints

- Backend: `GET http://localhost:8000/health/`
- OpenSearch: `GET https://localhost:9200/_cluster/health` (with auth)
- PostgreSQL: `docker exec cancerbot-postgres pg_isready -U cancerbot`

## Troubleshooting

### Containers can't reach Ollama

**Symptom:** Health check fails, "Ollama unavailable" in chat

**Solution:**
1. Verify Ollama is running: `curl http://localhost:11434/api/tags`
2. Verify it listens on all interfaces, not just loopback: `ss -ltnp | grep 11434` should show `*:11434` or `0.0.0.0:11434` (see "Install Ollama on host")
3. Check iptables service: `sudo systemctl status iptables-docker.service`
4. Manually apply rules: `sudo ./scripts/fix-iptables.sh`
5. Verify connectivity from the container (the image has no curl): `docker exec cancerbot-backend-1 python -c "import urllib.request; print(urllib.request.urlopen('http://172.30.0.1:11434/api/tags').status)"`

### Database connection errors

**Solution:**
1. Verify PostgreSQL is running: `docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot ps`
2. Check `.env` has correct `POSTGRES_PASSWORD`
3. Verify health check: `docker exec cancerbot-postgres pg_isready -U cancerbot`

### OpenSearch cluster issues

**Solution:**
```bash
# Check cluster status
docker exec opensearch-node1 curl -u admin:PASSWORD -k https://localhost:9200/_cluster/health

# Restart cluster
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot restart opensearch-node1 opensearch-node2
```

## Security Notes

- `.env` files are gitignored and never committed
- Secrets (passwords, API keys) are loaded from `.env` at runtime
- All connections between services use Docker network isolation
- OpenSearch requires authentication for all APIs
- PostgreSQL is not exposed outside the Docker network

## Additional Resources

- [CancerBot CLAUDE.md](CLAUDE.md) — Development guide and architecture
- [FastAPI Docs](https://fastapi.tiangolo.com/) — Backend framework
- [Docker Compose Docs](https://docs.docker.com/compose/) — Container orchestration
- [OpenSearch Docs](https://opensearch.org/docs/) — Vector search
