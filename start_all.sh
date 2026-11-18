#!/usr/bin/env bash
# SkillMate local launcher (Linux/macOS): MongoDB (Docker) -> backend -> frontend.
# Backend runs on 8001 (8000 is often taken by editor port-forwarding); the Next.js
# rewrite (BACKEND_URL in frontend/.env.local) already points there.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
LOGS="$ROOT/tmp/logs"
BE_PORT="${BE_PORT:-8001}"
FE_PORT="${FE_PORT:-3000}"
mkdir -p "$LOGS"

echo "==> MongoDB"
if docker ps -a --format '{{.Names}}' | grep -qx skillmate-mongo; then
  docker start skillmate-mongo >/dev/null
elif docker ps -a --format '{{.Names}}' | grep -qx level1-mongo; then
  docker start level1-mongo >/dev/null   # existing local container (same data)
else
  docker run -d --name skillmate-mongo -p 127.0.0.1:27017:27017 \
    -v skillmate_mongo_data:/data/db mongo:7.0 >/dev/null
fi

echo "==> Backend :$BE_PORT"
( cd "$ROOT/backend" && nohup .venv/bin/uvicorn main:app --port "$BE_PORT" >"$LOGS/backend.log" 2>&1 & )

echo "==> Frontend :$FE_PORT"
( cd "$ROOT/frontend" && nohup npm run dev -- --port "$FE_PORT" >"$LOGS/frontend.log" 2>&1 & )

sleep 8
curl -fsS "http://localhost:$BE_PORT/openapi.json" >/dev/null 2>&1 \
  && echo "backend ok" || echo "backend not answering yet, see $LOGS/backend.log"
echo "SkillMate: http://localhost:$FE_PORT   (logs in $LOGS)"
echo "Stop: pkill -f 'uvicorn main:app'; pkill -f 'next dev'"
