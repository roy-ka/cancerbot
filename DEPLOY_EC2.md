# Deploying CancerBot to AWS EC2

This is the EC2-specific part of a deployment. Everything after the instance exists — Docker, Ollama on the host, `.env`, `scripts/deploy.sh`, nginx — is the same as on any Ubuntu host and is covered in [DEPLOY_ORACLE_CLOUD.md](DEPLOY_ORACLE_CLOUD.md). Use the repository's own `docker-compose.yml` and `scripts/deploy.sh` unchanged; don't hand-write replacements.

## 1. Launch the instance

- **AMI:** Ubuntu 24.04 LTS
- **Memory:** 4 GB is the minimum. More is better: two OpenSearch nodes, PostgreSQL, Redis, the NLP service (scispaCy + a cross-encoder) and Ollama all run on this one host.
- **Disk:** at least **50 GB**. `scripts/deploy.sh` refuses to deploy with less than 10 GB free.
- **Security group, inbound:**
  - 22 (SSH) from your IP only
  - 80 and 443 from anywhere (nginx, Let's Encrypt)
  - **Nothing else.** The backend container publishes port 8000 on all interfaces so nginx can reach it; the security group is what keeps it off the internet. Every other service is bound to `127.0.0.1` by `docker-compose.yml`.

```bash
ssh -i your-key.pem ubuntu@<instance-public-ip>
```

## 2. Prepare the host

Follow [DEPLOY_ORACLE_CLOUD.md](DEPLOY_ORACLE_CLOUD.md) from "Initial Server Setup". The parts that matter on any host:

- **Docker** with the Compose v2 plugin (`docker compose`, not the legacy `docker-compose`).
- **Node.js 20.19+** — `deploy.sh` builds the frontend on the host.
- **Ollama on the host, listening on all interfaces.** Containers reach it through the Docker bridge gateway (`172.30.0.1`, set in `docker-compose.yml`), and the official installer binds to `127.0.0.1` only. Add `Environment="OLLAMA_HOST=0.0.0.0"` to the `ollama` systemd unit, restart it, then `ollama pull nomic-embed-text`. Port 11434 must stay closed in the security group.
- **`.env`** from `example.env`. In production you must set `ENV=production` and `FRONTEND_URL` (the backend refuses to start without it), plus `CORS_ORIGINS`, `JWT_SECRET`, `POSTGRES_PASSWORD`, `OPENSEARCH_INITIAL_ADMIN_PASSWORD`, `REDIS_PASSWORD`, `LLM_PROVIDER=groq`, `GROQ_API_KEY` and `BREVO_API_KEY`. Don't set `POSTGRES_URL`, `OPENSEARCH_URL`, `OLLAMA_URL`, `NLP_SERVICE_URL` or `REDIS_URL` for production — `docker-compose.yml` sets the in-network values itself.
- **OpenSearch TLS:** run `scripts/generate_opensearch_certs.sh` and set `OPENSEARCH_CA_CERT` (see "OpenSearch — Production SSL" in [CLAUDE.md](CLAUDE.md)).
- **`nginx.conf`** is deployment-specific. `deploy.sh` copies it into `/etc/nginx/sites-available/cancerbot` on every deploy, so edit the repository copy, never the installed one:
  - `root` — the built frontend, `<your checkout>/client/dist`
  - `ssl_certificate` / `ssl_certificate_key` — your domain's Let's Encrypt paths (next step)

## 3. HTTPS

Get a certificate without letting certbot rewrite the nginx config (the next deploy would overwrite its changes anyway):

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
sudo certbot certonly --nginx -d your-domain.com -d www.your-domain.com
sudo systemctl enable certbot.timer
```

Point the `ssl_certificate` lines in `nginx.conf` at `/etc/letsencrypt/live/your-domain.com/`, then deploy:

```bash
./scripts/deploy.sh
```

## 4. S3 backups (optional)

`scripts/daily_backup.sh` can upload PostgreSQL dumps to S3 when `BACKUP_S3_BUCKET` is set (see [BACKUP.md](BACKUP.md)). Use an instance IAM role rather than access keys:

1. **IAM → Roles → Create role**, trusted entity **EC2**, with this inline policy:

   ```json
   {
     "Version": "2012-10-17",
     "Statement": [
       {
         "Effect": "Allow",
         "Action": ["s3:PutObject", "s3:GetObject", "s3:DeleteObject", "s3:ListBucket"],
         "Resource": ["arn:aws:s3:::cancerbot-backups-*", "arn:aws:s3:::cancerbot-backups-*/*"]
       }
     ]
   }
   ```

2. Attach the role to the instance.
3. Create the bucket:

   ```bash
   aws s3 mb s3://cancerbot-backups-$(aws sts get-caller-identity --query Account --output text)
   ```

4. Install the backup dependencies on the host and schedule the job:

   ```bash
   pip3 install -r requirements-backup.txt
   (crontab -l 2>/dev/null; echo "0 2 * * * $PWD/scripts/daily_backup.sh >> /var/log/cancerbot_backup.log 2>&1") | crontab -
   ```

## Checking it's up

```bash
curl -i https://your-domain.com/health/   # 200 when PostgreSQL and Ollama are reachable, 503 otherwise
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot --profile prod ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml -p cancerbot --profile prod logs -f backend
```
