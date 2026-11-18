# SkillMate

AI-powered interview platform built by Softsuave's AI team. Panel members create question sets, assign interviews, and get AI-generated evaluations with PDF reports. Candidates take live voice/video interviews conducted by **Suvera AI**.

## Stack

- **Backend**: FastAPI, Beanie (MongoDB ODM), Motor, PyJWT, bcrypt
- **AI**: OpenAI / Gemini (provider-agnostic), TTS (Opus), STT (background transcription)
- **Real-time**: LiveKit WebRTC — AI bot, candidate, and panel member in a live room
- **Frontend**: Next.js 15, shadcn/ui, Tailwind, Zustand, Framer Motion, Web Audio API
- **Reports**: Jinja2 + WeasyPrint PDF generation (ReportLab fallback)

## Roles

| Role | Access |
|------|--------|
| **Super Admin** | Seeded on startup. Approves panel members, manages vault domains, views all data. Can watch live interviews (read-only). Can impersonate panel members via `X-Impersonate-User` header. |
| **Panel Member** | Signup + OTP + admin approval. Creates/forks question sets, manages candidates, assigns interviews, joins live sessions, views evaluations. |
| **Candidate** | Login via email + one-time access key. Takes live voice/video interview, auto-evaluated by AI. |

## Modules

### Auth & Admin
- Panel member signup with email OTP verification
- Admin approval/rejection workflow
- Candidate creation with one-time access keys
- JWT authentication (60 min panel member, 90 min candidate)
- Token blacklist for logout

### Question Sets
- Create empty drafts or fork from vault
- Add/edit/remove questions manually
- AI-generate single or bulk questions from prompts (with optional PDF upload)
- Guardrail system prevents off-topic or abusive prompts
- Finalize locks the set and auto-prepends a "Tell me about yourself" intro question (non-vault only)
- Min 5 questions to finalize

### Expert Vault
- 19 seeded domain categories across 3 umbrellas: Technology (11), BDE (4), HR (5)
- Admin creates and manages vault question sets per domain
- Panel members browse, view, and fork vault questions into their own sets
- Domain cards show ready question set count badges

### Vault Contributions
- Panel members request contribution access by selecting a domain
- Max 5 pending requests at a time
- Admin approves (generates JWT access key, 72h expiry) or rejects (with optional reason)
- Approved key visible to panel member with copy button
- Panel member activates key to create a vault draft, edits in the standard question set editor
- On finalize, key expires and the question set enters the vault permanently
- Unseen update notifications: red badge on sidebar Vault link and Contribute tab, clears on open

### Interviews
- Assign a finalized question set to a candidate by email
- Interview cards show candidate name (batch-loaded, not N+1)
- Delete cascades: deactivates sessions, removes answers
- Stale session detection on interview deletion

### Live Session (LiveKit)
- Real-time WebRTC room: AI bot + candidate + optional panel member
- AI bot (Suvera AI) joins as a background asyncio task, publishes TTS audio in Opus format
- Candidate's mic auto-mutes while AI speaks, unmutes when AI finishes
- Panel member starts as a **silent observer** (hidden token, invisible to candidate)
- Panel member can **join actively** — upgrades token, appears as a 4th card in the room
- Panel member can pause/resume the AI bot mid-interview
- **Admin is watch-only** — can observe live sessions but cannot join, mute, or control AI
- Lobby audio check: LLM-generated tech joke via TTS for speaker test, STT for mic verification
- Session resume: if candidate reconnects, existing room and AI bot are resumed

### Evaluation
- Triggered automatically on session completion as a background task
- Evaluates the **full transcript** — AI questions, panel follow-ups, and any extra panel questions beyond the prepared set
- **Multilingual**: transcript can be in any language; LLM evaluates in English
- `max_score` is always `len(prepared_questions) × 10` — fixed denominator regardless of how many questions were asked
- `percentage` capped at 100% even if panel extras push total score above max
- **Partial completion**: if the candidate exits before all AI questions are answered, status is `PARTIALLY_COMPLETED`; this is flagged on the evaluation card and detail page
- PDF reports generated with WeasyPrint (Jinja2 HTML templates); ReportLab as fallback
- Multilingual PDF: templates use Noto Sans / Noto Sans Tamil / DejaVu Sans font stack — requires `fonts-noto` on the server
- Both a detailed insights report and raw conversation transcript PDF are generated and emailed to candidate and panel member

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

## Interview Status Flow

```
FINALIZED → (session started) → live → (all questions done) → COMPLETED
                                     → (candidate exits early) → PARTIALLY_COMPLETED
```

## API Overview

~55 endpoints across 8 modules:

| Module | Prefix | Endpoints | Auth |
|--------|--------|-----------|------|
| Discovery | `/api/discovery` | 1 | Any |
| Auth | `/api/auth` | 8 | Mixed |
| Admin | `/api/admin` | 5 | Super Admin |
| Interviews | `/api/interviews` | 4 | Panel / Admin |
| Session | `/api/session` | 9 | Candidate |
| Evaluations | `/api/evaluations` | 3 | Panel / Admin |
| Vault | `/api/vault` | 17 | Mixed |
| Question Sets | `/api/question-sets` | 11 | Panel / Admin |

All responses wrapped in `GlobalResponse`:
```json
{ "success": true, "message": "...", "data": {}, "error": null }
```

## Setup

### Prerequisites
- Python 3.11+
- MongoDB 6+
- Node.js 18+ (frontend)
- LiveKit Server v1.9.12 — see [`live_kit_troubleshoot.md`](./live_kit_troubleshoot.md) for OS-specific notes
- `fonts-noto` system package (for multilingual PDF rendering with WeasyPrint)

### Backend

```bash
cd skill_mate
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
```

Create `.env`:

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
OPENAI_TTS_VOICE=nova

CORS_ORIGINS=["http://localhost:3000"]
```

### LiveKit Server

**Windows:**
1. Download `livekit-server.exe` (v1.9.12) and place it in the project root
2. Run:
```bash
livekit-server.exe --dev --keys "devkey: <your-LIVEKIT_API_SECRET>"
```

**Linux / macOS:**
```bash
curl -sSL https://get.livekit.io | bash
livekit-server --dev --keys "devkey: <your-LIVEKIT_API_SECRET>"
```

Add to `.env`:
```env
LIVEKIT_URL=ws://localhost:7880
LIVEKIT_API_KEY=devkey
LIVEKIT_API_SECRET=<your-secret>
```

> `--dev` enables local development mode. The CPU monitoring warning on Windows is harmless.
> For LAN testing see [`progress.md`](./progress.md) — LiveKit must run natively on Windows (not in Docker) for WebRTC ICE candidates to resolve correctly on LAN.

### Run the Backend

```bash
uvicorn app.main:app --reload --port 8000
```

On startup:
1. Connects to MongoDB, initializes Beanie with all document models
2. Initializes singleton clients (LLM, Email, TTS, STT)
3. Seeds 19 domain categories (idempotent)
4. Seeds super admin account

### Frontend

```bash
cd skill_mate_fe
npm install
npm run dev
```

Runs on `http://localhost:3000`.

## Architecture

```
app/
  _core/
    settings.py      # Pydantic BaseSettings, all config from env
    middleware.py     # GlobalResponse wrapper
    handler.py       # Exception handlers (HTTP, validation, generic)
    security.py      # JWT creation/decoding, vault key signing
  db/
    mongodb.py       # Motor + Beanie init, document model registry
  components/
    common/
      enums.py       # UmbrellaDomain, TechDomain, BDEDomain, HRDomain, DOMAIN_REGISTRY
      schemas.py     # Role, UserStatus, InterviewStatus, DifficultyLevel, etc.
    auth/            # routes, service, models, schemas, dependencies, blacklist
    admin/           # routes, service
    interview/       # routes, service, models, schemas
    question_set/    # routes, service, models, schemas, guardrail
    session/         # routes, service, models, ai_bot, transcript (LiveKit integration)
    evaluation/      # routes, service, models, schemas, prompt (PDF generation)
    vault/           # routes, service, models, schemas, seed
    discovery/       # routes (enum exposure)
    utils/           # llm_client, email_client, tts_client, stt_client, pdf_generator, logger
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

Admin can view the platform from any panel member's perspective:
- Send `X-Impersonate-User: {user_id}` header
- `get_effective_user` dependency resolves to the impersonated user
- Applied to shared routes (interviews, question sets, evaluations)
- Not applied to admin-only routes (vault management, admin panel)
