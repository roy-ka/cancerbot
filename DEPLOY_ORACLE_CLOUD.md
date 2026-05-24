# Deploying CancerBot to Oracle Cloud (Free Tier)

Oracle Cloud free tier gives you:
- 2x Ampere A1 Compute instances (4 OCPUs, 24GB RAM, ARM-based)
- 200GB block storage
- Object Storage (S3-compatible)
- Always free (no expiration)

## 1. Create Compute Instance

**From Oracle Cloud Console:**
1. Navigate to Compute → Instances
2. Click "Create Instance"
3. Name: `cancerbot`
4. Image & Shape:
   - Image: Ubuntu 24.04 LTS (Canonical)
   - Shape: Ampere (Always Free eligible)
   - OCPU: 4, Memory: 24GB
5. Networking:
   - Create new VCN or use existing
   - Assign public IP: Yes
6. SSH Key:
   - Download/use your SSH key
7. Click Create

**Wait ~5 minutes for instance to start**

## 2. Configure Network Security

**From VCN → Security Lists:**
1. Add Ingress Rules:
   - Port 22 (SSH): Your IP only
   - Port 80 (HTTP): 0.0.0.0/0
   - Port 443 (HTTPS): 0.0.0.0/0
   - Port 8000 (backend): 0.0.0.0/0 (optional, for testing)

## 3. SSH In

```bash
ssh -i your-key.pem ubuntu@your-instance-public-ip
```

## 4. Install Docker

```bash
sudo apt update && sudo apt install -y docker.io docker-compose

sudo usermod -aG docker $USER
# Log out and back in

docker --version
```

## 5. Clone & Configure

```bash
cd /opt
sudo git clone https://github.com/YOUR_REPO/cancerbot.git
cd cancerbot
sudo chown -R $USER:$USER .

cp .env.example .env
nano .env
```

**Key differences for Oracle Cloud:**

```bash
# Database
POSTGRES_PASSWORD=<generate-strong-password>
POSTGRES_URL=postgresql+asyncpg://cancerbot:PASSWORD@postgres:5432/cancerbot

# JWT
JWT_SECRET=<python3 -c "import secrets; print(secrets.token_urlsafe(32))">

# CORS
CORS_ORIGINS=https://your-domain.com

# Services (same as Docker Compose)
OLLAMA_URL=http://ollama:11434
NLP_URL=http://nlp_service:8011
OPENSEARCH_URL=https://opensearch:9200
OPENSEARCH_INITIAL_ADMIN_PASSWORD=<strong-password>

# SMTP
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-gmail@gmail.com
SMTP_PASSWORD=<app-password>
SMTP_FROM=noreply@your-domain.com

# Object Storage (instead of S3)
BACKUP_OBJECT_STORAGE_BUCKET=cancerbot-backups
BACKUP_OBJECT_STORAGE_NAMESPACE=<your-namespace>
BACKUP_OBJECT_STORAGE_REGION=<region-code>

ENV=production
```

**Get namespace & region:**
```bash
# From Oracle Cloud Console:
# 1. Object Storage → Buckets (note the "Namespace")
# 2. Top right corner shows region code (e.g., us-phoenix-1)
```

## 6. Docker Compose (Oracle-specific)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  postgres:
    image: postgres:16
    environment:
      POSTGRES_USER: cancerbot
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: cancerbot
    volumes:
      - postgres_data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD", "pg_isready", "-U", "cancerbot"]
      interval: 10s
      timeout: 5s
      retries: 5

  opensearch:
    image: opensearchproject/opensearch:latest
    environment:
      - discovery.type=single-node
      - OPENSEARCH_INITIAL_ADMIN_PASSWORD=${OPENSEARCH_INITIAL_ADMIN_PASSWORD}
      - OPENSEARCH_JAVA_OPTS=-Xms256m -Xmx256m
    volumes:
      - opensearch_data:/usr/share/opensearch/data
    ports:
      - "9200:9200"
    healthcheck:
      test: ["CMD", "curl", "-f", "-u", "admin:${OPENSEARCH_INITIAL_ADMIN_PASSWORD}", "http://localhost:9200"]
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

  backend:
    build:
      context: .
      dockerfile: Dockerfile
    environment:
      POSTGRES_URL: ${POSTGRES_URL}
      OPENSEARCH_URL: ${OPENSEARCH_URL}
      OPENSEARCH_INITIAL_ADMIN_PASSWORD: ${OPENSEARCH_INITIAL_ADMIN_PASSWORD}
      OLLAMA_URL: ${OLLAMA_URL}
      NLP_URL: ${NLP_URL}
      JWT_SECRET: ${JWT_SECRET}
      CORS_ORIGINS: ${CORS_ORIGINS}
      SMTP_HOST: ${SMTP_HOST}
      SMTP_PORT: ${SMTP_PORT}
      SMTP_USER: ${SMTP_USER}
      SMTP_PASSWORD: ${SMTP_PASSWORD}
      SMTP_FROM: ${SMTP_FROM}
      ENV: ${ENV}
    ports:
      - "8000:8000"
    depends_on:
      postgres:
        condition: service_healthy
      opensearch:
        condition: service_healthy
      ollama:
        condition: service_healthy
    command: uvicorn src.main:app --host 0.0.0.0 --port 8000

volumes:
  postgres_data:
  opensearch_data:
  ollama_data:
```

## 7. Create Dockerfile for Backend

Create `Dockerfile`:

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 8. Set Up Object Storage Backups

**Create bucket in Oracle Cloud Console:**
1. Object Storage → Buckets
2. Click "Create Bucket"
3. Name: `cancerbot-backups`
4. Standard tier
5. Click Create

**Create API key for backups:**
1. Profile → My Profile
2. API Keys → Add API Key
3. Download `.pem` file
4. Note the fingerprint and OCID

**Install OCI SDK:**
```bash
pip3 install oci

# Create ~/.oci/config (Oracle CLI config)
cat > ~/.oci/config << EOF
[DEFAULT]
user=<your-user-ocid>
fingerprint=<api-key-fingerprint>
key_file=~/.oci/your_api_key.pem
tenancy=<your-tenancy-ocid>
region=<region-code>
EOF

chmod 600 ~/.oci/config
cp your_api_key.pem ~/.oci/
```

**Update backup script for Oracle Object Storage:**

Create `scripts/backup_db_oracle.py`:

```python
#!/usr/bin/env python3
import subprocess
import os
from pathlib import Path
from datetime import datetime
import oci

def backup_to_file(output_path: Path):
    """Dump database to SQL file."""
    db_url = os.getenv("POSTGRES_URL")
    # Parse URL... (same as before)
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "pg_dump",
        "--format=custom",
        db_url.replace("postgresql+asyncpg://", "postgresql://"),
    ]
    
    subprocess.run(cmd, stdout=open(output_path, 'wb'), check=True)
    print(f"✓ Backup saved: {output_path}")
    return output_path

def backup_to_oracle_storage(local_path: Path):
    """Upload backup to Oracle Object Storage."""
    config = oci.config.from_file("~/.oci/config")
    object_storage = oci.object_storage.ObjectStorageClient(config)
    
    bucket = os.getenv("BACKUP_OBJECT_STORAGE_BUCKET")
    namespace = os.getenv("BACKUP_OBJECT_STORAGE_NAMESPACE")
    
    with open(local_path, 'rb') as f:
        object_storage.put_object(
            namespace_name=namespace,
            bucket_name=bucket,
            object_name=local_path.name,
            put_object_body=f,
        )
    
    print(f"✓ Uploaded to Oracle Object Storage: {bucket}/{local_path.name}")

if __name__ == "__main__":
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = Path("backups") / f"cancerbot_{timestamp}.dump"
    
    backup_to_file(backup_path)
    backup_to_oracle_storage(backup_path)
```

## 9. Deploy

```bash
# Build containers (first time)
docker-compose build

# Run migrations
docker-compose run backend alembic upgrade head

# Start all services
docker-compose up -d

# Check status
docker-compose logs -f backend
curl http://localhost:8000/health/
```

## 10. Set Up Nginx + HTTPS

```bash
sudo apt install -y nginx certbot python3-certbot-nginx

sudo certbot certonly --standalone -d your-domain.com
```

**Create `/etc/nginx/sites-available/cancerbot`:**

```nginx
server {
  listen 80;
  server_name your-domain.com;
  return 301 https://$server_name$request_uri;
}

server {
  listen 443 ssl http2;
  server_name your-domain.com;

  ssl_certificate /etc/letsencrypt/live/your-domain.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/your-domain.com/privkey.pem;

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

Enable:
```bash
sudo ln -s /etc/nginx/sites-available/cancerbot /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl restart nginx
sudo systemctl enable nginx
```

## 11. Monitor & Maintain

**Check backups:**
```bash
python3 scripts/backup_db_oracle.py
```

**View logs:**
```bash
docker-compose logs -f
```

**Restart services:**
```bash
docker-compose restart
```

**Health check:**
```bash
curl https://your-domain.com/health/
```

## Cost (Always Free)

- 2 Ampere instances: Free
- 200GB block storage: Free
- Object Storage: 20GB free/month (backups are small)
- Total: **$0/month** (if under free tier limits)

## Troubleshooting

**ARM architecture issues:**
If a Docker image doesn't support ARM (unlikely for standard images):
```bash
# Force x86 emulation (slower but works)
docker run --platform linux/amd64 image:tag
```

**Out of memory:**
```bash
# Check memory
free -h

# Reduce Java heap for OpenSearch
OPENSEARCH_JAVA_OPTS=-Xms128m -Xmx128m
```

**Disk full:**
```bash
df -h
du -sh /opt/cancerbot/

# Clean up old Docker images
docker image prune -a
```
