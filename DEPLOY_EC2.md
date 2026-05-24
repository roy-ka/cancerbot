# Deploying CancerBot to AWS EC2

## 1. EC2 Instance Setup

**Launch instance:**
- AMI: Ubuntu 24.04 LTS (t3.medium or larger for Ollama)
- Storage: 30+ GB (for embeddings + backups)
- Security group inbound rules:
  - Port 80: HTTP (from 0.0.0.0/0, for Let's Encrypt)
  - Port 443: HTTPS (from 0.0.0.0/0)
  - Port 22: SSH (from your IP)

**SSH in:**
```bash
ssh -i your-key.pem ubuntu@your-instance-ip
```

## 2. Install Docker & Docker Compose

```bash
sudo apt update && sudo apt install -y docker.io docker-compose

# Add ubuntu user to docker group (no sudo needed)
sudo usermod -aG docker $USER
# Log out and back in for group membership to take effect

# Verify
docker --version
docker-compose --version
```

## 3. Clone & Configure

```bash
cd /opt
sudo git clone https://github.com/YOUR_REPO/cancerbot.git
cd cancerbot
sudo chown -R $USER:$USER .

# Create .env
cp .env.example .env
nano .env  # Fill in all values (see below)
```

**Required .env values for EC2:**
```
# Database
POSTGRES_PASSWORD=<generate-strong-password>
POSTGRES_USER=cancerbot
POSTGRES_DB=cancerbot
POSTGRES_URL=postgresql+asyncpg://cancerbot:PASSWORD@postgres:5432/cancerbot

# Secrets
JWT_SECRET=<generate-with: python3 -c "import secrets; print(secrets.token_urlsafe(32))">

# URLs
CORS_ORIGINS=https://your-domain.com
OLLAMA_URL=http://ollama:11434
NLP_URL=http://nlp_service:8011

# OpenSearch (from Docker service)
OPENSEARCH_URL=https://opensearch:9200
OPENSEARCH_INITIAL_ADMIN_PASSWORD=<generate-strong-password>

# SMTP (for password reset emails)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=<your-gmail>
SMTP_PASSWORD=<app-password>
SMTP_FROM=noreply@your-domain.com

# S3 Backups
BACKUP_S3_BUCKET=cancerbot-backups-<account-id>

# Dev/Prod
ENV=production
```

## 4. Docker Compose

Update `docker-compose.yml` for production:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "${POSTGRES_USER}"]
      interval: 10s
      timeout: 5s
      retries: 5

  opensearch:
    image: opensearchproject/opensearch:latest
    environment:
      - discovery.type=single-node
      - OPENSEARCH_INITIAL_ADMIN_PASSWORD=${OPENSEARCH_INITIAL_ADMIN_PASSWORD}
      - OPENSEARCH_JAVA_OPTS=-Xms512m -Xmx512m
    volumes:
      - opensearch_data:/usr/share/opensearch/data
    ports:
      - "9200:9200"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9200"]
      interval: 10s
      timeout: 5s
      retries: 5

  ollama:
    image: ollama/ollama:latest
    volumes:
      - ollama_data:/root/.ollama
    ports:
      - "11434:11434"
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:11434/api/tags"]
      interval: 30s
      timeout: 10s
      retries: 3

  nlp_service:
    build:
      context: ./nlp_service
      dockerfile: Dockerfile
    environment:
      NLP_DATABASE_URL: ${NLP_DATABASE_URL}
    depends_on:
      postgres:
        condition: service_healthy
    ports:
      - "8011:8011"

volumes:
  postgres_data:
  opensearch_data:
  ollama_data:
```

## 5. AWS IAM Role for S3 Backups

**Create IAM role:**
1. Go to IAM → Roles → Create role
2. Trusted entity: EC2
3. Add inline policy:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::cancerbot-backups-*",
        "arn:aws:s3:::cancerbot-backups-*/*"
      ]
    }
  ]
}
```
4. Attach role to your EC2 instance

**Create S3 bucket:**
```bash
aws s3 mb s3://cancerbot-backups-$(aws sts get-caller-identity --query Account --output text)
```

## 6. Deploy Script

Create `deploy.sh`:

```bash
#!/bin/bash
set -e

cd /opt/cancerbot

echo "Pulling latest code..."
git pull origin main

echo "Building containers..."
docker-compose build

echo "Running migrations..."
docker-compose run --rm backend alembic upgrade head

echo "Starting services..."
docker-compose up -d

echo "Waiting for services to be ready..."
sleep 10

echo "Running health check..."
curl -f http://localhost:8000/health/ || { echo "Health check failed"; exit 1; }

echo "✓ Deployment complete"
```

Make executable:
```bash
chmod +x deploy.sh
```

Deploy:
```bash
./deploy.sh
```

## 7. SSL/HTTPS (Let's Encrypt)

```bash
sudo apt install -y certbot python3-certbot-nginx

sudo certbot certonly --standalone -d your-domain.com -d www.your-domain.com

# Auto-renew
sudo systemctl enable certbot.timer
```

## 8. Nginx Reverse Proxy

```bash
sudo apt install -y nginx
```

Create `/etc/nginx/sites-available/cancerbot`:

```nginx
upstream backend {
  server localhost:8000;
}

server {
  listen 80;
  server_name your-domain.com www.your-domain.com;
  return 301 https://$server_name$request_uri;
}

server {
  listen 443 ssl http2;
  server_name your-domain.com www.your-domain.com;

  ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

  location / {
    proxy_pass http://backend;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_read_timeout 300s;
    proxy_connect_timeout 300s;

    # WebSocket support
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
  }
}
```

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/cancerbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
```

## 9. Automated Backups

```bash
# Install boto3 inside the instance
pip3 install boto3

# Add to crontab (backup daily at 2am)
(crontab -l 2>/dev/null; echo "0 2 * * * /opt/cancerbot/scripts/daily_backup.sh >> /var/log/cancerbot_backup.log 2>&1") | crontab -

# Check cron logs
sudo tail -f /var/log/cancerbot_backup.log
```

## 10. Monitoring

**Health check endpoint:**
```bash
curl https://your-domain.com/health/
```

**Check logs:**
```bash
docker-compose logs -f backend
docker-compose logs -f ollama
```

**Disk usage:**
```bash
df -h
du -sh /opt/cancerbot
```

## Troubleshooting

**Backend won't start:**
```bash
docker-compose logs backend
docker-compose run backend python -c "import src.main"
```

**Ollama not ready:**
```bash
docker-compose exec ollama ollama list
docker-compose exec ollama ollama pull llama3.1:8b
```

**Database migration failed:**
```bash
docker-compose run backend alembic upgrade head
```

**No backups happening:**
```bash
/opt/cancerbot/scripts/backup_db.py  # Test manually
sudo tail -f /var/log/cancerbot_backup.log
```
