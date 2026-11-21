from contextlib import asynccontextmanager

from fastapi import FastAPI
from starlette.requests import Request as StarletteRequest
from starlette.responses import Response as StarletteResponse

from app._core.handler import register_exception_handlers
from app._core.middleware import GlobalResponseMiddleware
from app._core.settings import settings
from app.components.utils.logger import log


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    from app.db.mongodb import close_db, init_db
    from app.components.auth.blacklist import ensure_ttl_index
    from app.components.utils.email_client import init_email_client
    from app.components.utils.llm_client import init_llm_client

    log.info("Starting %s...", settings.APP_NAME)
    await init_db()
    log.info("MongoDB connected")

    init_llm_client()
    init_email_client()

    await ensure_ttl_index()
    log.info("All singletons initialized")

    yield

    from app.components.utils.llm_client import get_llm_client

    for close_fn in (get_llm_client,):
        try:
            await close_fn().close()
        except Exception:
            pass

    await close_db()
    log.info("Shutdown complete")


app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# CORS — handle manually to avoid middleware ordering issues
ALLOWED_ORIGINS = set(settings.CORS_ORIGINS)


@app.middleware("http")
async def cors_middleware(request: StarletteRequest, call_next):
    origin = request.headers.get("origin", "")

    # Preflight
    if request.method == "OPTIONS":
        response = StarletteResponse(status_code=200)
        response.headers["Access-Control-Allow-Origin"] = origin if origin in ALLOWED_ORIGINS else ""
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS, PATCH"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization, X-Impersonate-User"
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Access-Control-Allow-Private-Network"] = "true"
        response.headers["Access-Control-Max-Age"] = "600"
        return response

    response = await call_next(request)

    if origin in ALLOWED_ORIGINS:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"

    return response

app.add_middleware(GlobalResponseMiddleware)

# Exception handlers
register_exception_handlers(app)

# Routers
from app.components.auth.routes import router as auth_router
from app.components.hiring.routes import router as hiring_router
from app.components.sourcing.routes import router as sourcing_router
from app.components.level1.routes import router as level1_router

app.include_router(auth_router, prefix="/api")
app.include_router(hiring_router, prefix="/api")
app.include_router(sourcing_router, prefix="/api")
app.include_router(level1_router, prefix="/api")
