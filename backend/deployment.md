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
   │                              └── api.skillmate.com    → Backend   (:8000)
   │
   └── 80 TCP (HTTP) ──────────► Nginx (redirect → HTTPS)

Internal (not exposed):
   ├── MongoDB :27017
   ├── Frontend :3000
   └── Backend :8000
```

All services run in a single `docker-compose.yml` on one Linux server.

---

## Prerequisites

- Linux server (Ubuntu 22.04+ recommended)
- Docker Engine 24+ & Docker Compose v2
- Domain with DNS access
- Minimum specs: 4 vCPU, 8 GB RAM, 40 GB SSD (scales with concurrent exam candidates)

---

## 1. DNS Configuration

Create **2 A records** pointing to the server's public IP:

| Subdomain               | Type | Value             |
|--------------------------|------|-------------------|
| `app.skillmate.com`      | A    | `<SERVER_PUBLIC_IP>` |
| `api.skillmate.com`      | A    | `<SERVER_PUBLIC_IP>` |

---

## 2. Firewall Rules

Open **2 ports** only:

| Port   | Protocol | Purpose                        |
|--------|----------|--------------------------------|
| 80     | TCP      | HTTP → HTTPS redirect          |
| 443    | TCP      | HTTPS/WSS (all web traffic)    |

**Do NOT expose**: 27017 (MongoDB), 8000 (Backend), 3000 (Frontend)

---

## 3. Directory Structure

```
/opt/skillmate/
├── docker-compose.yml
├── .env
├── nginx/
│   └── nginx.conf
├── certbot/                  # auto-created by certbot
│   ├── conf/
│   └── www/
└── level1_files/             # exam uploads: resumes, photos, proctoring screenshots
```

---

## 4. Environment File (`.env`)

```env
# MongoDB
MONGO_URI=mongodb://mongo:27017

# JWT
JWT_SECRET=<generate-a-64-char-random-string>
JWT_ALGORITHM=HS256

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
```

---

## 5. Nginx Configuration (`nginx/nginx.conf`)

```nginx
events {
    worker_connections 1024;
}

http {
    # Redirect HTTP → HTTPS
    server {
        listen 80;
        server_name app.skillmate.com api.skillmate.com;

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

    map $http_upgrade $upgrade_type {
        default upgrade;
        ''      '';
    }
}
```

---

## 6. Docker Compose (`docker-compose.yml`)

```yaml
services:

  mongo:
    image: mongo:7
    volumes:
      - mongo_data:/data/db
    restart: unless-stopped

  backend:
    build: .
    env_file:
      - .env
    depends_on:
      - mongo
    volumes:
      - ./level1_files:/app/level1_files
    restart: unless-stopped

  frontend:
    build: ../skill_mate_fe
    environment:
      - NEXT_PUBLIC_API_URL=https://api.skillmate.com
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

---

## 7. SSL Certificates (Let's Encrypt)

### Initial Setup (before Nginx starts with SSL)

First, temporarily comment out the SSL server blocks in `nginx.conf` and start Nginx with only port 80.

```bash
# Start nginx (HTTP only) and certbot
docker compose up -d nginx

# Issue certificates for both subdomains
docker compose run --rm certbot certonly \
  --webroot --webroot-path=/var/www/certbot \
  -d app.skillmate.com \
  -d api.skillmate.com \
  --email devops@skillmate.com \
  --agree-tos --no-eff-email
```

Then restore the full `nginx.conf` with SSL blocks and restart:

```bash
docker compose restart nginx
```

Certbot container auto-renews every 12 hours.

---

## 8. Deployment Steps

```bash
# 1. Clone repos
git clone <backend-repo> /opt/skillmate
git clone <frontend-repo> /opt/skill_mate_fe

# 2. Set up config files
cd /opt/skillmate
cp .env.example .env         # edit with production values
mkdir -p nginx level1_files

# 3. Place nginx.conf
# Copy the nginx config from Section 6 into nginx/nginx.conf

# 4. Set up SSL (see Section 7)

# 5. Launch everything
docker compose up -d --build

# 6. Verify
docker compose ps              # all services running
docker compose logs backend    # check for startup errors
curl https://api.skillmate.com/health   # backend health check
```

---

## 9. Health Checks

| Service  | Check                                      |
|----------|--------------------------------------------|
| Frontend | `curl https://app.skillmate.com`            |
| Backend  | `curl https://api.skillmate.com/health`     |
| MongoDB  | `docker compose exec mongo mongosh --eval "db.runCommand({ping:1})"` |

---

## 10. Backups

```bash
# MongoDB dump
docker compose exec mongo mongodump --out /data/backup
docker cp $(docker compose ps -q mongo):/data/backup ./backups/$(date +%F)
```

Schedule via cron for daily backups.

---

## 11. Updating

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
| Server ports exposed  | 80, 443                        |
| Subdomains            | app / api .skillmate.com       |
| MongoDB               | Internal only, port 27017      |
| SSL                   | Let's Encrypt, auto-renew      |
| Logs                  | `docker compose logs -f <service>` |