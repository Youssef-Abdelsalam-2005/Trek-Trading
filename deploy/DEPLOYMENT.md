# Trek Trading — Production Deployment

Target: Hetzner VPS, CX32 (4 vCPU / 8 GB RAM) minimum. Ubuntu 24.04 LTS.

## 1. Initial Server Setup

```bash
# Update system
apt update && apt upgrade -y

# Create service users
useradd --system --shell /usr/sbin/nologin --create-home --home-dir /var/lib/trek-api trek-api
useradd --system --shell /usr/sbin/nologin --create-home --home-dir /var/lib/trek-worker trek-worker
useradd --system --shell /usr/sbin/nologin --create-home --home-dir /var/lib/trek-engine trek-engine
useradd --system --shell /usr/sbin/nologin --create-home --home-dir /var/lib/trek-signer trek-signer

# Shared group for signer socket access (engine only — NOT api)
groupadd trek-shared
usermod -aG trek-shared trek-engine
usermod -aG trek-shared trek-signer
```

## 2. Install Dependencies

```bash
# Python 3.12
apt install -y python3.12 python3.12-venv python3.12-dev build-essential

# Docker (for Postgres and gVisor sandbox)
apt install -y docker.io docker-compose-v2
systemctl enable --now docker

# gVisor runtime
apt install -y apt-transport-https ca-certificates curl gnupg
curl -fsSL https://gvisor.dev/archive.key | gpg --dearmor -o /usr/share/keyrings/gvisor-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/gvisor-archive-keyring.gpg] https://storage.googleapis.com/gvisor/releases release main" > /etc/apt/sources.list.d/gvisor.list
apt update && apt install -y runsc

# Register gVisor as Docker runtime
cat > /etc/docker/daemon.json <<'EOF'
{
  "runtimes": {
    "runsc": {
      "path": "/usr/bin/runsc"
    }
  }
}
EOF
systemctl restart docker

# Verify gVisor works
docker run --rm --runtime=runsc hello-world

# Nginx reverse proxy
apt install -y nginx certbot python3-certbot-nginx
```

## 3. Application Setup

```bash
# Create app directory and deploy code
mkdir -p /opt/trek/logs
cd /opt/trek
git clone https://github.com/Youssef-Abdelsalam-2005/Trek-Trading.git .

# Create virtualenv and install
python3.12 -m venv .venv
.venv/bin/pip install ./backend

# Set ownership
chown -R root:root /opt/trek
chmod -R 755 /opt/trek
chown trek-api:trek-api /opt/trek/logs
chmod 1770 /opt/trek/logs
```

## 4. Configure Secrets

### Database

```bash
mkdir -p /etc/trek
# Generate a strong password — replace DB_PASSWORD below
DB_PASSWORD=$(openssl rand -base64 32)

cat > /etc/trek/db.env <<EOF
POSTGRES_USER=trek
POSTGRES_PASSWORD=${DB_PASSWORD}
POSTGRES_DB=trek
EOF
chmod 600 /etc/trek/db.env

DATABASE_URL="postgresql+asyncpg://trek:${DB_PASSWORD}@127.0.0.1:5432/trek"
```

### API

```bash
cat > /etc/trek/api.env <<EOF
DATABASE_URL=${DATABASE_URL}
SESSION_SECRET=$(openssl rand -hex 32)
EOF
chmod 600 /etc/trek/api.env
chown root:trek-api /etc/trek/api.env
```

### Worker

```bash
cat > /etc/trek/worker.env <<EOF
DATABASE_URL=${DATABASE_URL}
EOF
chmod 600 /etc/trek/worker.env
chown root:trek-worker /etc/trek/worker.env
```

### Engine

```bash
cat > /etc/trek/engine.env <<EOF
DATABASE_URL=${DATABASE_URL}
SIGNER_SOCKET=/run/trek-signer/sign.sock
EOF
chmod 600 /etc/trek/engine.env
chown root:trek-engine /etc/trek/engine.env
```

### Signer

```bash
mkdir -p /etc/trek-signer
# WALLET_ENCRYPTION_KEY: Fernet key used to decrypt the wallet keypair at startup.
# Generate with: python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
cat > /etc/trek-signer/signer.env <<EOF
WALLET_ENCRYPTION_KEY=<your-fernet-key-here>
EOF
chmod 600 /etc/trek-signer/signer.env
chown root:trek-signer /etc/trek-signer/signer.env

# Place the encrypted wallet key
# The encrypted blob is created offline — never put the plaintext key on the server.
cp /path/to/wallet.key.enc /var/lib/trek-signer/wallet.key.enc
chown trek-signer:trek-signer /var/lib/trek-signer/wallet.key.enc
chmod 600 /var/lib/trek-signer/wallet.key.enc
```

## 5. Start Postgres

```bash
cp /opt/trek/deploy/docker-compose.prod.yml /opt/trek/docker-compose.prod.yml
cd /opt/trek
docker compose -f docker-compose.prod.yml up -d

# Wait for healthy
docker compose -f docker-compose.prod.yml ps

# Run migrations
DATABASE_URL="${DATABASE_URL}" .venv/bin/alembic -c backend/alembic.ini upgrade head
```

## 6. Install systemd Units

```bash
cp /opt/trek/deploy/trek-api.service /etc/systemd/system/
cp /opt/trek/deploy/trek-worker.service /etc/systemd/system/
cp /opt/trek/deploy/trek-engine.service /etc/systemd/system/
cp /opt/trek/deploy/trek-signer.service /etc/systemd/system/

systemctl daemon-reload

systemctl enable --now trek-signer
systemctl enable --now trek-engine
systemctl enable --now trek-worker
systemctl enable --now trek-api
```

Verify all services are running:

```bash
systemctl status trek-api trek-worker trek-engine trek-signer
```

Check signer socket permissions:

```bash
ls -la /run/trek-signer/sign.sock
# Expected: srw-rw---- trek-signer trek-shared
```

## 7. Firewall

```bash
bash /opt/trek/deploy/ufw-setup.sh
```

This allows SSH (22), HTTP (80), and HTTPS (443) only. The API listens on 127.0.0.1:8000 — not exposed directly; Nginx proxies to it.

## 8. Nginx Reverse Proxy

```bash
cat > /etc/nginx/sites-available/trek <<'EOF'
server {
    listen 80;
    server_name your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location /api/events {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header Connection '';
        proxy_http_version 1.1;
        chunked_transfer_encoding off;
        proxy_buffering off;
        proxy_cache off;
    }
}
EOF

ln -sf /etc/nginx/sites-available/trek /etc/nginx/sites-enabled/trek
rm -f /etc/nginx/sites-enabled/default
nginx -t && systemctl reload nginx

# TLS via Let's Encrypt
certbot --nginx -d your-domain.com
```

## 9. Verify

```bash
# All services running
systemctl is-active trek-api trek-worker trek-engine trek-signer

# API responds
curl -s http://127.0.0.1:8000/health
# {"status":"ok"}

# Postgres reachable
docker compose -f /opt/trek/docker-compose.prod.yml exec db pg_isready -U trek

# Firewall active
ufw status

# Signer hardening score
systemd-analyze security trek-signer.service
```

## 10. Updates

To deploy a new version of the API without affecting the execution engine:

```bash
cd /opt/trek
git pull origin main
.venv/bin/pip install ./backend

# Only restart API and worker — engine stays up (C8)
systemctl restart trek-api trek-worker
```

To update the engine (will briefly interrupt live trading loops — state is persisted in DB):

```bash
systemctl restart trek-engine
```

To update the signer (will briefly prevent new transaction signing):

```bash
systemctl restart trek-signer
```
