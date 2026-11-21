# SkillMate

AI-powered hiring platform built by Softsuave's AI team. A job description is analysed, matching profiles are sourced from Naukri ResDex, and shortlisted candidates take an AI-generated, proctored **Level 1 exam**. Results are scored automatically and emailed to the candidate.

## Stack

- **Backend**: FastAPI, Beanie (MongoDB ODM), Motor, PyJWT, bcrypt
- **AI**: OpenAI / Gemini (provider-agnostic) for JD analysis, screening, question generation and essay scoring
- **Frontend**: Next.js, shadcn/ui, Tailwind, Zustand; MediaPipe face detection for exam proctoring

## Roles

| Role | Access |
|------|--------|
| **Super Admin** | Single admin from `SUPER_ADMIN_EMAIL` / `SUPER_ADMIN_PASSWORD`. Manages JDs, sourcing, the Level 1 exam and results. Can impersonate users via the `X-Impersonate-User` header. |
| **Candidate** | Logs in with email + Level 1 access key (emailed on invite). Takes the proctored exam. |

## Hiring flow

```
JD -> Naukri sourcing -> selected profiles -> Level 1 exam -> scored result email -> final report
```

1. **JD + sourcing** (`/api/sourcing`) - see below.
2. **Selection** - shortlisted profiles with contact details are auto-selected (`HIRING_AUTO_SELECT`) and become SkillMate candidates.
3. **Level 1** (`/api/level1`) - AI agents analyse the profile, generate questions and build the assessment; candidates get an invite with an access key. MCQs are scored in Python, essays by the LLM. The result email is sent only after every answer is evaluated.
4. **Result** (`/api/hiring`) - a score strictly above `LEVEL1_PASS_PERCENT` (default 75) is recorded as `passed`, otherwise `failed` (or `terminated` for malpractice). The admin sees every candidate's status, score and result email state on one page.

Level 1 keys are reusable until they expire (`LEVEL1_KEY_TTL_HOURS`, or exam submission), so reconnects work.

## Modules

- `auth` - super admin login, candidate login (Level 1 key), JWT with a blacklist for logout
- `sourcing` - JD analysis, ResDex search plan, profile screening and scoring
- `level1` - question bank, assessment, proctored exam, scoring, live monitoring websocket, reports
- `hiring` - orchestration between sourcing and Level 1, activity feed, result emails

### Naukri Sourcing (`/api/sourcing`, page `/sourcing`)
- Separate from JD Analyze. A panel member adds a JD (text or PDF/DOCX); three AI agents (one structured call each, model = `OPENAI_MODEL`): **JD Analyst** (requirements), **Search Strategist** (ResDex Boolean keyword strings), **Candidate Screener** (per-skill evidence). Scores are computed in code (`sourcing/scoring.py`): a missing mandatory skill → 0; a similar substitute skill → −10; base 60 plus bonuses; capped at 100; threshold 60.
- **Source from Naukri** adds up to 5 matches per click, in this order:
  1. screened matches already waiting in the pool;
  2. profiles read earlier but not screened yet (screened in page-sized groups, stopping once 5 are found);
  3. ResDex, **page by page**: the SkillMate Sourcing extension fills ResDex's search form, sends one result page (~40 profiles), SkillMate screens it (batches of 10, 4 in parallel) and shortlists. Fewer than 5 so far → it asks for the next page (at most 5 pages). Once 5 are found it reads 2 more pages straight into the pool, so the next click needs no ResDex.
  A Naukri profile is stored once per JD; rejected people never come back. The next click continues from the next unread page.
- **Select** reveals contact details through the extension (1 ResDex credit) and creates the SkillMate candidate. Not logged in to ResDex → popup "Login with Naukri ResDex to continue extraction."
- **Extension setup:** load `softsuave_hire_extension_v2.1.1/skillmate_sourcing` unpacked (the dedicated SkillMate Sourcing extension, not the parent Softsuave Hire one). SkillMate's address is `SKILLMATE_URL` / `SKILLMATE_API_ORIGINS` in its `config.js`; the same origins must be listed in its `manifest.json` (bridge `content_scripts` matches + `host_permissions`). Reload the extension after changing them.
- Settings: `SOURCING_BATCH_SIZE` (5), `SOURCING_MIN_SCORE` (60), `SOURCING_PAGES_PER_RUN` (5, pages read while looking for 5), `SOURCING_PREFETCH_PAGES` (2), `SOURCING_MAX_PAGE` (20), `SOURCING_SCREEN_CHUNK` (10 profiles per call), `SOURCING_SCREEN_CONCURRENCY` (4), `SOURCING_RUN_TIMEOUT_MINUTES` (20, since the run's last activity), `LLM_MAX_TOKENS_SOURCING` (32000 — reasoning models such as gpt-6-luna spend part of it on hidden reasoning; 25 profiles per call overflowed 8192 and came back empty).
- Tests: `pip install -r requirements-dev.txt` then `pytest` (uses a throwaway `skill_mate_test` database on `MONGO_URI`).

#### LinkedIn as a second source
- A **separate** extension, `linkedin_sourcing/` (repo root), reads LinkedIn people search the same page-by-page way. It shares nothing with the Naukri extension at runtime (own `LINKEDIN_*` messages, storage and pages) — see its README. The backend only knows a run's `source` (`naukri` | `linkedin`): `POST /sourcing/jds/{id}/runs` takes `{"source": "linkedin"}` (default `naukri`); the page endpoint, screening and scoring are shared.
- **Naukri first, LinkedIn as the fallback** — decided by the page (`source-button.tsx`): LinkedIn is used when the Naukri extension is missing, ResDex isn't logged in, or a Naukri run fails (CAPTCHA, form not found, no results…) and the LinkedIn extension is installed and logged in. Screened matches already in the pool are served first, whatever the source.
- **Paging is kept per source** (`next_page`/`pool_exhausted` for Naukri, `linkedin_next_page`/`linkedin_exhausted` for LinkedIn); a new search plan resets both. LinkedIn is read more gently: `SOURCING_LINKEDIN_PAGES_PER_RUN` (4, ~10 people a page), `SOURCING_LINKEDIN_PREFETCH_PAGES` (1), `SOURCING_LINKEDIN_MAX_PAGE` (20).
- **Searches that match nobody are broadened, not failed.** The JD analyst no longer lists soft skills ("Communication skills", "Problem-solving"…) as skills (prompt + `agents._SOFT_SKILL`), and the search is built from the 5 most central mandatory skills (`SEARCH_MAX_SKILLS`); screening still checks all of them. On LinkedIn the extension additionally sanitises and relaxes whatever plan it gets (`linkedin_sourcing/core.js › searchLevels`) when the first page is empty, and reports the step that worked as `search_level`; SkillMate keeps it in `linkedin_search_level` so later pages continue on the same search. A new analysis or search plan resets it.
- **LinkedIn cards are thin** (headline, location, a snippet — no skills list, years or CTC). The screener marks a mandatory skill it can't see as `unverified` instead of `absent` (enforced in code by `scoring.apply_source_rules`, for LinkedIn only): the profile is still scored, with a "verify" note, and Naukri keeps its strict rule.
- **One email per person.** Profiles are stored once per JD by link (LinkedIn links are normalised to `linkedin.com/in/<name>`) and, when the page shows an email, by email — so the same person on both sources is not added twice. A LinkedIn card never shows an email, so the duplicate is normally caught at selection: if both copies are selected, `hiring.ensure_candidate` reuses the first hiring row (candidates are created by email), so Level 1 invites and result emails go out once. `sync_level1` also drops a second waiting row for the same email.
- **A LinkedIn candidate is only taken with an email.** The extension (`EMAIL_ONLY`, default on; v1.2.0+) limits the search to 1st-degree connections, opens each one's contact dialog and posts only the people it got an email for, plus `scanned` (how many cards the page had) so a page nobody shared an email on still counts as read. `receive_profiles` refuses a LinkedIn profile without an email whatever sent it (`no_email` in the response); `SourcingRun.profiles_scanned` vs `profiles_received` shows how many were looked at and how many kept. `SOURCING_LINKEDIN_PREFETCH_PAGES` is 0: every candidate costs a profile view. The page refuses extension builds older than 1.2.0.
- **No auto-invite for LinkedIn candidates.** Every shortlisted LinkedIn candidate has an email, so `HIRING_AUTO_SELECT` would invite each one the moment a run ends. `HIRING_AUTO_SELECT_LINKEDIN` (default `False`) exempts them: they are selected, and invited, only when the recruiter clicks Select. Naukri behaviour is unchanged.

## API Overview

| Module | Prefix | Auth |
|--------|--------|------|
| Auth | `/api/auth` | Mixed |
| Sourcing | `/api/sourcing` | Admin |
| Hiring | `/api/hiring` | Admin |
| Level 1 | `/api/level1` | Admin (management) / Level 1 candidate (exam) |

All responses wrapped in `GlobalResponse`:
```json
{ "success": true, "message": "...", "data": {}, "error": null }
```

## Setup

### Prerequisites
- Python 3.11+
- MongoDB 6+
- Node.js 18+ (frontend)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in the values. The essentials:

```env
MONGO_URI=mongodb://localhost:27017
MONGO_DB_NAME=skill_mate

JWT_SECRET_KEY=your-secret-key

SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password

SUPER_ADMIN_EMAIL=admin@skillmate.com
SUPER_ADMIN_PASSWORD=your-admin-password

LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-4o

CORS_ORIGINS=["http://localhost:3000"]
```

Unknown keys in `.env` are ignored, so an older file that still has LiveKit, TTS or STT entries keeps working.

### Run the Backend

```bash
uvicorn main:app --reload --port 8000
```

On startup the backend connects to MongoDB, initializes Beanie with all document models, and initializes the LLM and Email singletons.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Runs on `http://localhost:3000`.

## Architecture

```
app/
  _core/
    settings.py      # Pydantic BaseSettings, all config from env
    middleware.py    # GlobalResponse wrapper
    handler.py       # Exception handlers (HTTP, validation, generic)
    security.py      # JWT creation/decoding
  db/
    mongodb.py       # Motor + Beanie init, document model registry
  components/
    common/          # schemas (Role, UserStatus, GlobalResponse)
    auth/            # routes, service, models, schemas, dependencies, blacklist
    sourcing/        # JD analysis, search plan, screening, scoring
    level1/          # AI exam: agents, assessment, candidate exam, scoring, proctoring, websocket
    hiring/          # routes, service, models (orchestration and result emails)
    utils/           # llm_client, email_client, resume_parser, logger
  main.py            # App entry, lifespan, CORS, router registration
```

**Conventions:**
- Each module: `routes.py`, `service.py`, `models.py`, `schemas.py`
- Pydantic BaseSettings for config (never `os.environ`)
- Singleton pattern for all external clients
- Single-line docstrings
- Provider-agnostic LLM client (swap OpenAI/Gemini via env var)

## CORS

Custom middleware (not `CORSMiddleware`) to handle Chrome private network access:
- Responds to `Access-Control-Request-Private-Network` with `Access-Control-Allow-Private-Network: true`
- Required for Chrome to allow requests from public pages to local/private network APIs
- `X-Impersonate-User` included in allowed headers

## Impersonation

The super admin can view the platform as another user:
- Send `X-Impersonate-User: {user_id}` header
- `get_effective_user` dependency resolves to the impersonated user
