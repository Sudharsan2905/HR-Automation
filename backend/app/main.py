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
    from app.components.utils.tts_client import init_tts_client
    from app.components.utils.stt_client import init_stt_client
    from app.components.utils.livekit_service import init_livekit_service

    log.info("Starting %s...", settings.APP_NAME)
    await init_db()
    log.info("MongoDB connected")

    init_llm_client()
    init_email_client()
    init_tts_client()
    init_stt_client()
    init_livekit_service()

    await ensure_ttl_index()
    log.info("All singletons initialized")

    yield

    from app.components.session.service import cleanup_all_bots
    from app.components.utils.llm_client import get_llm_client
    from app.components.utils.tts_client import get_tts_client
    from app.components.utils.stt_client import get_stt_client
    from app.components.utils.livekit_service import get_livekit_service

    await cleanup_all_bots()

    for close_fn in (get_llm_client, get_tts_client, get_stt_client, get_livekit_service):
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
from app.components.common.routes import router as discovery_router
from app.components.auth.routes import router as auth_router
from app.components.hiring.routes import router as hiring_router
from app.components.interview.routes import router as interview_router
from app.components.session.routes import router as session_router
from app.components.evaluation.routes import router as evaluation_router
from app.components.question_set.routes import router as question_set_router
from app.components.jd_interview.routes import router as jd_interview_router
from app.components.sourcing.routes import router as sourcing_router
from app.components.level1.routes import router as level1_router

app.include_router(discovery_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(hiring_router, prefix="/api")
app.include_router(interview_router, prefix="/api")
app.include_router(session_router, prefix="/api")
app.include_router(evaluation_router, prefix="/api")
app.include_router(question_set_router, prefix="/api")
app.include_router(jd_interview_router, prefix="/api")
app.include_router(sourcing_router, prefix="/api")
app.include_router(level1_router, prefix="/api")
