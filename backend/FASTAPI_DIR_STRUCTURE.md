## FastAPI Project Structure

Follow this directory structure for all my FastAPI projects. Each domain module follows the pattern: `routes.py → schemas.py → service.py → models.py`.

```
project-root/
├── .env                          # Secrets & config (never committed)
├── .env.example                  # Placeholder template for onboarding
├── .gitignore
├── .dockerignore
├── .pre-commit-config.yaml
├── Dockerfile
├── docker-compose.yml
├── pyproject.toml                # Dependencies + tool configs (ruff, pytest)
├── requirements.txt
├── requirements-dev.txt
├── CLAUDE.md
│
├── .github/workflows/
│   ├── ci.yml
│   └── deploy.yml
│
├── scripts/                      # One-off ops scripts (seed, migrate, etc.)
├── logs/                         # Runtime logs (gitignored)
│
├── tests/                        # Mirrors app/ structure
│   ├── conftest.py               # Shared fixtures (test client, mock DB, auth)
│   ├── api/                      # Route-level integration tests
│   ├── service/                  # Service-level tests
│   └── unit/                     # Pure unit tests
│
└── app/
    ├── main.py                   # Entry point — lifespan, middleware, router registration
    │
    ├── core/                     # Framework infrastructure (not a feature)
    │   ├── settings.py           # Pydantic BaseSettings env config
    │   ├── exceptions.py         # Domain exceptions (NotFound, AccessDenied, etc.)
    │   ├── handler.py            # Global exception → response mapping
    │   ├── middleware.py         # Response wrapper, request ID generation
    │   ├── dependencies.py       # Shared FastAPI deps (get_db, get_current_user re-exports)
    │   └── decorator.py          # Utility decorators
    │
    ├── auth/                     # Auth is top-level — it's cross-cutting
    │   ├── client.py             # JWT validation, JWKS, token decoding
    │   ├── dependencies.py       # get_current_user, require_role
    │   ├── redis_client.py       # Session lookup
    │   ├── models.py             # UserRole enum
    │   ├── schemas.py            # Auth DTOs
    │   ├── routes.py             # /verify, /me, /assign-role
    │   └── service.py
    │
    ├── db/                       # Database connection layer
    │   ├── mongodb.py            # MongoDB/Beanie connection manager
    │   └── chroma_client.py      # Vector store client
    │
    ├── common/                   # Cross-cutting enums & shared schemas (not a feature)
    │   ├── enums.py              # Platform, Country, Status — used across modules
    │   └── schemas.py            # GlobalResponse[T] wrapper
    │
    ├── utils/                    # Shared clients & helpers (not a feature)
    │   ├── gemini_client.py      # LLM client
    │   ├── embeddings.py         # Embedding generation
    │   ├── gcs_client.py         # Cloud storage
    │   ├── hash_utils.py         # Content hashing for caching & dedup
    │   └── logger.py             # Structured logging setup
    │
    ├── tracing/                  # Request tracing (separated from rate limiting)
    │   ├── context.py            # TraceContext via contextvars
    │   ├── middleware.py         # Per-request trace creation
    │   ├── decorators.py         # @trace_enabled, @retry_on_failure
    │   ├── models.py
    │   ├── schemas.py
    │   ├── routes.py             # Admin trace lookup
    │   └── service.py
    │
    ├── rate_limiting/            # Rate limiting (own concern, own package)
    │   ├── limiter.py            # Redis sliding-window with Lua scripts
    │   ├── decorators.py         # @rate_limit
    │   ├── admin_config.py       # Load configs from DB
    │   ├── models.py
    │   ├── schemas.py
    │   ├── routes.py
    │   └── service.py
    │
    └── modules/                  # Domain feature modules
        │                         # Each module: routes → schemas → service → models
        │
        ├── billing/
        │   ├── models.py         # Plan, CreditBalance, CreditTransaction, Order
        │   ├── schemas.py        # DTOs for plans, credits, orders
        │   ├── routes.py         # Public plans, user credits, admin management
        │   ├── service.py        # PlanService, CreditService, OrderService
        │   ├── payment_gateway.py
        │   └── defaults.py       # Seed data for default plans
        │
        ├── chat/
        │   ├── models.py         # ChatSession, ChatMessage
        │   ├── schemas.py        # ChatMode enum, message DTOs
        │   ├── routes.py         # SSE streaming endpoints
        │   └── service.py        # Mode dispatch, RAG retrieval, streaming
        │
        ├── compliance/
        │   ├── models.py         # ComplianceCheck
        │   ├── schemas.py        # Check request/response, media items
        │   ├── routes.py         # /check, /history, /suggestions
        │   ├── service.py        # RAG-powered analysis with content-hash caching
        │   └── prompt.py         # Prompt builder (when module-specific)
        │
        ├── ingestion/
        │   ├── models.py         # RagFeed, PlatformRule, CountryRule
        │   ├── schemas.py        # DocumentType, upload metadata
        │   ├── routes.py         # PDF upload, feed listing, rule actions
        │   └── service.py        # Parse, chunk, embed, store
        │
        ├── prompt/
        │   ├── enum.py           # ModuleType, BasePromptName
        │   ├── models.py         # DynamicPrompt, BasePrompt
        │   ├── schemas.py        # Prompt CRUD DTOs
        │   ├── routes.py         # Admin prompt management
        │   ├── service.py        # CRUD with platform/country filtering
        │   └── defaults.py       # All hardcoded fallback templates in one file
        │
        ├── token_usage/
        │   ├── context.py        # Per-request token accumulator via contextvars
        │   ├── models.py         # TokenUsageLog, TokenUsageAggregate
        │   ├── schemas.py        # Cost breakdowns by operation/model
        │   ├── routes.py         # /summary, /aggregate, /history
        │   └── service.py        # Persist & aggregate by period
        │
        └── <new_module>/         # Add new features here following the same pattern
            ├── models.py
            ├── schemas.py
            ├── routes.py
            └── service.py
```

### Rules
- **Every domain module** lives under `modules/` and follows `routes → schemas → service → models`
- **Cross-cutting concerns** (`auth/`, `common/`, `utils/`, `tracing/`, `rate_limiting/`) stay at `app/` level — they are NOT features
- **`core/`** is pure framework plumbing — settings, exceptions, middleware, shared deps
- **`common/`** holds enums and schemas imported by multiple modules
- **`utils/`** holds external client wrappers (LLM, storage, embeddings) — no business logic
- **Config files** (`.env`, `Dockerfile`, `pyproject.toml`, etc.) live at project root, not inside `app/`
- **Tests** mirror `app/` structure under `tests/` at the root
- Never put secrets in `.env.example` — only placeholder keys