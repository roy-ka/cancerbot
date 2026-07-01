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
git clone https://github.com/roy-ka/cancerbot-private.git
cd cancerbot-private
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env with your values
nano .env
```

Key variables:
- `OPENSEARCH_INITIAL_ADMIN_PASSWORD` — OpenSearch admin password
- `POSTGRES_PASSWORD` — PostgreSQL password
- `OLLAMA_URL` — Points to Ollama running on host (e.g., http://localhost:11434)
- `JWT_SECRET` — Session secret
- Other API keys and settings as needed

### 3. Install Ollama on host

Ollama runs on the host (not in Docker) for GPU acceleration:

```bash
# On Ubuntu, follow: https://github.com/ollama/ollama/blob/main/README.md
curl -fsSL https://ollama.ai/install.sh | sh

# Pull a model
ollama pull llama3.1:8b
ollama pull nomic-embed-text

# Start Ollama service
systemctl start ollama
systemctl enable ollama
```

Verify Ollama is accessible from the Docker network:
```bash
curl http://localhost:11434/api/tags
```

## Docker Deployment

### 1. Build and start services

```bash
docker compose build
docker compose up -d
```

Verify services are running:
```bash
docker compose ps
```

### 2. Run database migrations

```bash
docker run --rm \
  --network cancerbot_osnet \
  --env-file .env \
  -v $(pwd):/app -w /app \
  python:3.12-slim bash -c \
  "pip install -q alembic psycopg2-binary sqlalchemy python-dotenv && alembic upgrade head"
```

### 3. Test health endpoints

```bash
# Backend health check
curl http://localhost:8000/health/

# Expected response:
# {"status":"ok","checks":{"database":"ok","ollama":"ok"}}
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

Setup Nginx as a reverse proxy to expose the FastAPI backend on port 80/443:

```bash
sudo apt-get install -y nginx

# Use the provided setup script (requires certbot SSL certs already installed)
sudo ./scripts/setup-nginx.sh
```

Example configuration (managed by `scripts/setup-nginx.sh`):
```nginx
server {
    listen 80;
    server_name cancer-bot.com www.cancer-bot.com;
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name cancer-bot.com www.cancer-bot.com;

    ssl_certificate /etc/letsencrypt/live/cancer-bot.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/cancer-bot.com/privkey.pem;

    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

Enable the site:
```bash
sudo ln -s /etc/nginx/sites-available/cancerbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
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
docker compose ps
docker compose stats
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
2. Check iptables service: `sudo systemctl status iptables-docker.service`
3. Manually apply rules: `sudo ./scripts/fix-iptables.sh`
4. Verify connectivity from container: `docker exec cancerbot-backend-1 curl http://host.docker.internal:11434/api/tags`

### Database connection errors

**Solution:**
1. Verify PostgreSQL is running: `docker compose ps`
2. Check `.env` has correct `POSTGRES_PASSWORD`
3. Verify health check: `docker exec cancerbot-postgres pg_isready -U cancerbot`

### OpenSearch cluster issues

**Solution:**
```bash
# Check cluster status
docker exec opensearch-node1 curl -u admin:PASSWORD -k https://localhost:9200/_cluster/health

# Restart cluster
docker compose restart opensearch-node1 opensearch-node2
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
