# SkillMate — Production Deployment Guide

> **Audience**: DevOps / Infrastructure team
> **Approach**: Single server, fully dockerized via `docker-compose`

---

## Architecture Overview

```
Internet
   │
   ├── 443 TCP (HTTPS/WSS) ──► Nginx (reverse proxy)
   │                              ├── app.skillmate.com    → Frontend  (:3000)
   │                              ├── api.skillmate.com    → Backend   (:8000)
   │                              └── livekit.skillmate.com → LiveKit  (:7880)
   │
   ├── 80 TCP (HTTP) ──────────► Nginx (redirect → HTTPS)
   │
   ├── 7882 UDP ───────────────► LiveKit (WebRTC media — primary)
   │
   └── 7881 TCP ───────────────► LiveKit (WebRTC media — TCP fallback)

Internal (not exposed):
   ├── MongoDB :27017
   ├── Frontend :3000
   ├── Backend :8000
   └── LiveKit signaling :7880
```

All services run in a single `docker-compose.yml` on one Linux server.

---

## Prerequisites

- Linux server (Ubuntu 22.04+ recommended)
- Docker Engine 24+ & Docker Compose v2
- Domain with DNS access
- Minimum specs: 4 vCPU, 8 GB RAM, 40 GB SSD (scales with concurrent interviews)

---

## 1. DNS Configuration

Create **3 A records** pointing to the server's public IP:

| Subdomain               | Type | Value             |
|--------------------------|------|-------------------|
| `app.skillmate.com`      | A    | `<SERVER_PUBLIC_IP>` |
| `api.skillmate.com`      | A    | `<SERVER_PUBLIC_IP>` |
| `livekit.skillmate.com`  | A    | `<SERVER_PUBLIC_IP>` |

---

## 2. Firewall Rules

Open **4 ports** only:

| Port   | Protocol | Purpose                        |
|--------|----------|--------------------------------|
| 80     | TCP      | HTTP → HTTPS redirect          |
| 443    | TCP      | HTTPS/WSS (all web traffic)    |
| 7881   | TCP      | LiveKit WebRTC TCP fallback    |
| 7882   | UDP      | LiveKit WebRTC media (primary) |

**Do NOT expose**: 27017 (MongoDB), 8000 (Backend), 3000 (Frontend), 7880 (LiveKit WS)

---

## 3. Directory Structure

```
/opt/skillmate/
├── docker-compose.yml
├── .env
├── livekit.yaml
├── nginx/
│   └── nginx.conf
├── certbot/                  # auto-created by certbot
│   ├── conf/
│   └── www/
├── reports/                  # generated PDF reports
└── recordings/               # interview recordings (future)
```

---

## 4. Environment File (`.env`)

```env
# MongoDB
MONGO_URI=mongodb://mongo:27017

# JWT
JWT_SECRET=<generate-a-64-char-random-string>
JWT_ALGORITHM=HS256

# LiveKit
LIVEKIT_API_KEY=skillmate_prod
LIVEKIT_API_SECRET=<generate-a-36-char-minimum-secret>
LIVEKIT_URL=ws://livekit:7880
LIVEKIT_CLIENT_URL=wss://livekit.skillmate.com

# LLM Provider (OpenAI or Gemini)
OPENAI_API_KEY=<your-openai-key>

# Email (SMTP)
SMTP_HOST=<smtp-host>
SMTP_PORT=587
SMTP_USER=<smtp-user>
SMTP_PASSWORD=<smtp-password>
MAIL_FROM=noreply@skillmate.com

# Frontend
NEXT_PUBLIC_API_URL=https://api.skillmate.com
NEXT_PUBLIC_LIVEKIT_URL=wss://livekit.skillmate.com
```

> **Note**: `LIVEKIT_URL` is internal (container-to-container). `LIVEKIT_CLIENT_URL` is what browsers connect to (goes through Nginx as WSS).

---

## 5. LiveKit Configuration (`livekit.yaml`)

```yaml
port: 7880
rtc:
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: true
keys:
  skillmate_prod: <same-secret-as-LIVEKIT_API_SECRET-in-env>
logging:
  level: info
```

> `use_external_ip: true` — LiveKit resolves the server's public IP via STUN and advertises it in ICE candidates. This is required for clients to reach the media ports.

---

## 6. Nginx Configuration (`nginx/nginx.conf`)

```nginx
events {
    worker_connections 1024;
}

http {
    # Redirect HTTP → HTTPS
    server {
        listen 80;
        server_name app.skillmate.com api.skillmate.com livekit.skillmate.com;

        location /.well-known/acme-challenge/ {
            root /var/www/certbot;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # Frontend
    server {
        listen 443 ssl;
        server_name app.skillmate.com;

        ssl_certificate     /etc/letsencrypt/live/app.skillmate.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/app.skillmate.com/privkey.pem;

        location / {
            proxy_pass http://frontend:3000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }

    # Backend API
    server {
        listen 443 ssl;
        server_name api.skillmate.com;

        ssl_certificate     /etc/letsencrypt/live/api.skillmate.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/api.skillmate.com/privkey.pem;

        client_max_body_size 50M;

        location / {
            proxy_pass http://backend:8000;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }

    # LiveKit Signaling (WSS)
    server {
        listen 443 ssl;
        server_name livekit.skillmate.com;

        ssl_certificate     /etc/letsencrypt/live/livekit.skillmate.com/fullchain.pem;
        ssl_certificate_key /etc/letsencrypt/live/livekit.skillmate.com/privkey.pem;

        location / {
            proxy_pass http://livekit:7880;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $upgrade_type;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_read_timeout 86400;
        }
    }

    map $http_upgrade $upgrade_type {
        default upgrade;
        ''      '';
    }
}
```

---

## 7. Docker Compose (`docker-compose.yml`)

```yaml
services:

  mongo:
    image: mongo:7
    volumes:
      - mongo_data:/data/db
    restart: unless-stopped

  livekit:
    image: livekit/livekit-server:v1.9
    network_mode: host
    volumes:
      - ./livekit.yaml:/etc/livekit.yaml
    command: --config /etc/livekit.yaml
    restart: unless-stopped

  backend:
    build: .
    env_file:
      - .env
    depends_on:
      - mongo
    volumes:
      - ./reports:/app/reports
      - ./recordings:/app/recordings
    restart: unless-stopped

  frontend:
    build: ../skill_mate_fe
    environment:
      - NEXT_PUBLIC_API_URL=https://api.skillmate.com
      - NEXT_PUBLIC_LIVEKIT_URL=wss://livekit.skillmate.com
    restart: unless-stopped

  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./certbot/conf:/etc/letsencrypt:ro
      - ./certbot/www:/var/www/certbot:ro
    depends_on:
      - frontend
      - backend
    restart: unless-stopped

  certbot:
    image: certbot/certbot
    volumes:
      - ./certbot/conf:/etc/letsencrypt
      - ./certbot/www:/var/www/certbot
    entrypoint: "/bin/sh -c 'trap exit TERM; while :; do certbot renew; sleep 12h & wait $${!}; done;'"
    restart: unless-stopped

volumes:
  mongo_data:
```

> **Important**: LiveKit uses `network_mode: host` so it binds directly to the server's network interfaces. This is required for WebRTC ICE candidates to contain the correct public IP. Because of this, LiveKit is **not** on the Docker bridge network — the backend reaches it via `LIVEKIT_URL=ws://livekit:7880` won't work. Use `ws://127.0.0.1:7880` or `ws://host.docker.internal:7880` instead if needed.

---

## 8. SSL Certificates (Let's Encrypt)

### Initial Setup (before Nginx starts with SSL)

First, temporarily comment out the SSL server blocks in `nginx.conf` and start Nginx with only port 80.

```bash
# Start nginx (HTTP only) and certbot
docker compose up -d nginx

# Issue certificates for all 3 subdomains
docker compose run --rm certbot certonly \
  --webroot --webroot-path=/var/www/certbot \
  -d app.skillmate.com \
  -d api.skillmate.com \
  -d livekit.skillmate.com \
  --email devops@skillmate.com \
  --agree-tos --no-eff-email
```

Then restore the full `nginx.conf` with SSL blocks and restart:

```bash
docker compose restart nginx
```

Certbot container auto-renews every 12 hours.

---

## 9. Deployment Steps

```bash
# 1. Clone repos
git clone <backend-repo> /opt/skillmate
git clone <frontend-repo> /opt/skill_mate_fe

# 2. Set up config files
cd /opt/skillmate
cp .env.example .env         # edit with production values
cp livekit.example.yaml livekit.yaml  # edit with production secret
mkdir -p nginx reports recordings

# 3. Place nginx.conf
# Copy the nginx config from Section 6 into nginx/nginx.conf

# 4. Set up SSL (see Section 8)

# 5. Launch everything
docker compose up -d --build

# 6. Verify
docker compose ps              # all services running
docker compose logs backend    # check for startup errors
docker compose logs livekit    # check LiveKit bound correctly
curl https://api.skillmate.com/health   # backend health check
```

---

## 10. LiveKit `network_mode: host` — What It Means

Since LiveKit runs with `network_mode: host`, it shares the host's network stack directly:

- It does **not** join the Docker bridge network
- Other containers cannot reach it via service name `livekit`
- Backend must use `LIVEKIT_URL=ws://172.17.0.1:7880` (Docker bridge gateway) or `ws://127.0.0.1:7880` if backend also uses host network
- Ports 7880, 7881, 7882 are bound on the host automatically (no `ports:` mapping needed)
- Nginx reaches LiveKit at `http://172.17.0.1:7880` (or host IP) for WSS proxying

Update `.env` accordingly:
```env
LIVEKIT_URL=ws://172.17.0.1:7880
```

---

## 11. Health Checks

| Service  | Check                                      |
|----------|--------------------------------------------|
| Frontend | `curl https://app.skillmate.com`            |
| Backend  | `curl https://api.skillmate.com/health`     |
| LiveKit  | `curl http://localhost:7880`                |
| MongoDB  | `docker compose exec mongo mongosh --eval "db.runCommand({ping:1})"` |

---

## 12. Backups

```bash
# MongoDB dump
docker compose exec mongo mongodump --out /data/backup
docker cp $(docker compose ps -q mongo):/data/backup ./backups/$(date +%F)
```

Schedule via cron for daily backups.

---

## 13. Updating

```bash
cd /opt/skillmate
git pull origin main

cd /opt/skill_mate_fe
git pull origin main

cd /opt/skillmate
docker compose up -d --build
```

Zero-downtime is not supported in this single-server setup. Expect ~30 seconds of downtime during rebuild.

---

## Quick Reference

| Item                  | Value                          |
|-----------------------|--------------------------------|
| Server ports exposed  | 80, 443, 7881 (TCP), 7882 (UDP) |
| Subdomains            | app / api / livekit .skillmate.com |
| MongoDB               | Internal only, port 27017      |
| SSL                   | Let's Encrypt, auto-renew      |
| LiveKit networking    | `network_mode: host`           |
| Logs                  | `docker compose logs -f <service>` |