"""
SkillMate reverse proxy — single-port entry point for ngrok.

Routing table
  /api/{path}       →  http://localhost:8000  (FastAPI BE, /api prefix kept)
  /*                →  http://localhost:3000  (Next.js FE)
  /*         [WS]   →  ws://localhost:3000    (Next.js HMR)
"""

import asyncio
import logging
from contextlib import asynccontextmanager

import httpx
import websockets
from fastapi import FastAPI, Request, WebSocket
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)-8s  %(message)s")
logger = logging.getLogger("proxy")

BACKEND     = "http://localhost:8000"
FRONTEND    = "http://localhost:3000"
FRONTEND_WS = "ws://localhost:3000"

# Must not be forwarded across HTTP hops (RFC 7230 §6.1)
_HOP = frozenset({
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade",
    "sec-websocket-key", "sec-websocket-accept",
    "sec-websocket-extensions", "sec-websocket-version",
})


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120.0, connect=10.0),
        follow_redirects=True,
        limits=httpx.Limits(max_connections=200, max_keepalive_connections=50),
    ) as client:
        app.state.http = client
        logger.info("SkillMate proxy ready  →  http://0.0.0.0:8080")
        yield


app = FastAPI(title="SkillMate Proxy", lifespan=lifespan)


# ── HTTP helper ───────────────────────────────────────────────────────────────

async def http_proxy(request: Request, upstream_base: str, strip_prefix: str = "") -> Response:
    path = request.url.path
    if strip_prefix:
        path = path[len(strip_prefix):] or "/"

    url = httpx.URL(f"{upstream_base}{path}")
    if request.url.query:
        url = url.copy_with(query=request.url.query.encode())

    headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in _HOP and k.lower() != "host"
    }

    upstream_req = request.app.state.http.build_request(
        method=request.method,
        url=url,
        headers=headers,
        content=await request.body(),
    )

    try:
        resp = await request.app.state.http.send(upstream_req, stream=True)
    except httpx.RequestError as exc:
        logger.warning("HTTP proxy error → %s : %s", upstream_base, exc)
        return Response(content=f"Upstream unreachable: {exc}", status_code=502)

    resp_headers = {k: v for k, v in resp.headers.items() if k.lower() not in _HOP}
    return StreamingResponse(
        resp.aiter_raw(),
        status_code=resp.status_code,
        headers=resp_headers,
        background=BackgroundTask(resp.aclose),
    )


# ── WebSocket helper ──────────────────────────────────────────────────────────

async def ws_proxy(client: WebSocket, upstream_uri: str) -> None:
    await client.accept()
    logger.debug("WS  %s  →  %s", client.url.path, upstream_uri)

    forward_headers = [
        (k, v) for k, v in client.headers.items()
        if k.lower() not in _HOP and k.lower() != "host"
    ]

    try:
        async with websockets.connect(
            upstream_uri,
            additional_headers=forward_headers,
            max_size=2**24,      # 16 MB — large enough for proctoring frames
            ping_interval=None,  # let the application layer manage pings
        ) as upstream:
            done = asyncio.Event()

            async def client_to_upstream() -> None:
                try:
                    while not done.is_set():
                        msg = await client.receive()
                        if msg["type"] == "websocket.disconnect":
                            break
                        if msg.get("bytes"):
                            await upstream.send(msg["bytes"])
                        elif msg.get("text"):
                            await upstream.send(msg["text"])
                except Exception:
                    pass
                finally:
                    done.set()
                    try:
                        await upstream.close()
                    except Exception:
                        pass

            async def upstream_to_client() -> None:
                try:
                    async for msg in upstream:
                        if done.is_set():
                            break
                        if isinstance(msg, bytes):
                            await client.send_bytes(msg)
                        else:
                            await client.send_text(msg)
                except Exception:
                    pass
                finally:
                    done.set()

            await asyncio.gather(client_to_upstream(), upstream_to_client(), return_exceptions=True)

    except Exception as exc:
        logger.debug("WS proxy %s : %s", upstream_uri, exc)
    finally:
        try:
            await client.close()
        except Exception:
            pass


# ── Routes (most-specific first) ─────────────────────────────────────────────

# Backend — /api prefix is kept (BE routes already include it)
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def be_proxy(request: Request, path: str):
    return await http_proxy(request, BACKEND)


# Frontend WebSocket (Next.js HMR / fast-refresh)
@app.websocket("/{path:path}")
async def fe_ws(ws: WebSocket, path: str):
    qs = f"?{ws.url.query}" if ws.url.query else ""
    await ws_proxy(ws, f"{FRONTEND_WS}/{path}{qs}")


# Frontend HTTP — root + everything else
@app.api_route("/", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def fe_root(request: Request):
    return await http_proxy(request, FRONTEND)


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"])
async def fe_proxy(request: Request):
    return await http_proxy(request, FRONTEND)
