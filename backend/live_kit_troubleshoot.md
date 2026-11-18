# LiveKit in Docker — OS Limitations & Workarounds

> **LiveKit Server Version: v1.9.12**

## The Problem

LiveKit uses **WebRTC** for real-time audio/video. WebRTC relies on **ICE candidates** — IP addresses that clients use to connect. When LiveKit runs inside Docker, ICE candidates advertise the **container's internal IP** (e.g., `172.18.0.2`), which is unreachable from the host machine or LAN devices.

---

## OS Scenarios

### Linux — Docker Works Fine

| Item | Detail |
|------|--------|
| **Status** | LiveKit runs in Docker without issues |
| **Why** | `network_mode: host` is fully supported — container shares the host's network stack directly |
| **ICE candidates** | Advertise the host's real IP (e.g., `192.168.1.10`) |
| **Setup** | Standard Docker Compose with `network_mode: host` |

```yaml
services:
  livekit:
    image: livekit/livekit-server
    network_mode: host
    volumes:
      - ./livekit.yaml:/etc/livekit.yaml
    command: --config /etc/livekit.yaml --bind 0.0.0.0
```

---

### Windows / macOS — Docker Does NOT Work

| Item | Detail |
|------|--------|
| **Status** | LiveKit in Docker fails for WebRTC connections |
| **Why** | Docker Desktop runs containers inside a hidden Linux VM. `network_mode: host` binds to the VM's network, not the host machine's network |
| **ICE candidates** | Advertise the VM/container internal IP — unreachable from host or LAN |

**What was tried and failed (Windows):**

1. `network_mode: host` — binds to VM, not Windows host
2. `rtc.node_ip` config — LiveKit v1.9.12 ignores this for ICE candidates inside Docker
3. `use_external_ip: true` — resolves to public IP via STUN, unreachable on LAN
4. TURN relay inside Docker — same networking isolation issue
5. Port mapping (`ports: 7880:7880`) — works for WebSocket signaling but NOT for WebRTC UDP/TCP media traffic

---

## Workaround for Windows / macOS

**Run LiveKit as a native binary on the host OS.** Keep the backend in Docker — only LiveKit needs to run natively.

### Step 1: Download LiveKit Server

Download the binary for your OS from [LiveKit Releases](https://github.com/livekit/livekit/releases):
- Windows: `livekit-server-windows-amd64.zip`
- macOS: `livekit-server-darwin-arm64.tar.gz` (Apple Silicon) or `livekit-server-darwin-amd64.tar.gz`

### Step 2: Create `livekit.yaml`

```yaml
port: 7880
rtc:
  tcp_port: 7881
  udp_port: 7882
  use_external_ip: false
keys:
  devkey: secretsecretsecretsecretsecretsecret
logging:
  level: info
```

> **Note:** The API secret must be 32+ characters. The native binary enforces this.

### Step 3: Run LiveKit natively

```bash
# Windows (PowerShell)
.\livekit-server.exe --config livekit.yaml --bind 0.0.0.0

# macOS
./livekit-server --config livekit.yaml --bind 0.0.0.0
```

### Step 4: Configure the backend (Docker) to reach native LiveKit

In `docker-compose.yml`:

```yaml
services:
  backend:
    environment:
      - LIVEKIT_URL=ws://host.docker.internal:7880        # backend -> LiveKit (internal)
      - LIVEKIT_CLIENT_URL=ws://<YOUR_LAN_IP>:7880         # frontend browser -> LiveKit (external)
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

In `.env`:

```
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=secretsecretsecretsecretsecretsecret
```

### Step 5: Open firewall ports (for LAN access)

```powershell
# Windows — run as Administrator
New-NetFirewallRule -DisplayName "LiveKit WS" -Direction Inbound -Protocol TCP -LocalPort 7880 -Action Allow
New-NetFirewallRule -DisplayName "LiveKit RTC TCP" -Direction Inbound -Protocol TCP -LocalPort 7881 -Action Allow
New-NetFirewallRule -DisplayName "LiveKit RTC UDP" -Direction Inbound -Protocol UDP -LocalPort 7882 -Action Allow
```

---

## URL Configuration Reference

| Variable | Used By | Value (Docker backend + native LiveKit) |
|----------|---------|----------------------------------------|
| `LIVEKIT_URL` | Backend (server-side) | `ws://host.docker.internal:7880` |
| `LIVEKIT_CLIENT_URL` | Frontend (browser) | `ws://<LAN_IP>:7880` |
| `LIVEKIT_API_KEY` | Backend | `devkey` |
| `LIVEKIT_API_SECRET` | Backend | `secretsecretsecretsecretsecretsecret` |

---

## Quick Reference

| OS | LiveKit in Docker? | Workaround |
|----|-------------------|------------|
| **Linux** | Yes (`network_mode: host`) | None needed |
| **Windows** | No | Run `livekit-server.exe` natively |
| **macOS** | No | Run `livekit-server` binary natively |

## Startup Order

1. **LiveKit** (native binary) — must be running first
2. **Backend** (`docker-compose up`) — connects to LiveKit via `host.docker.internal`
3. **Frontend** (`npm run dev`) — browsers connect to LiveKit via LAN IP
