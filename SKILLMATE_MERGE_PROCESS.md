# SkillMate + Level 1 merge: process

Goal: one product (SkillMate) with one login, one backend, one frontend. Level 1 (AI-generated
exam) becomes a module inside SkillMate; Level 2 is SkillMate's existing voice interview.

## Target flow
1. **JD submitted** in SkillMate Sourcing (exists): JD analysis -> search plan -> Naukri ResDex via the browser extension -> screened/scored profiles.
2. **Approval = SkillMate's existing "selected" profile status** (decision: no separate meeting step). Selecting profiles starts Level 1.
3. **Level 1** (from our app): for the selected profiles, the Talent Orchestrator agents run for the approved profiles (analysis -> shared 20 questions -> assessment -> invites). Candidates take the proctored exam; MCQs scored in Python, essays by the LLM; result email only after every answer is evaluated.
4. **Level 2** (exists): candidates scoring **above 75%** in Level 1 are assigned automatically (decision) via `jd-interviews/{id}/assign` -> LiveKit session -> evaluation + PDF report. Pass mark: `LEVEL1_PASS_PERCENT=75`, strictly greater than (exactly 75% does not advance), configurable.
5. Admin sees both levels per candidate in one place.

## What exists vs what is new
| Piece | Status |
|---|---|
| Sourcing (JD -> profiles) | exists in SkillMate |
| Level 2 voice interview | exists in SkillMate |
| Login | SkillMate: super admin from env, interviewers via Softsuave ERP, candidates by email + access key |
| Level 1 exam, agents, scoring, proctoring | in level1-backend / level1-frontend; to be ported |
| Approval | reuse sourcing `selected` status (no new meeting entity) |
| Level progression (L1 -> L2) | NEW: automatic by pass mark |

## Phases (each one is reviewable and leaves SkillMate working)
**Phase 0 - Safety.** New branch in `SkillMate` git (`feature/level1-merge`). Leave `level1-*` untouched until the end. Run the existing SkillMate sourcing tests as a baseline.

**Phase 1 - Backend foundation.**
- New component `backend/app/components/level1/` (routes/service/schemas, SkillMate layout; single-line docstrings, low complexity per DEVELOPMENT_STANDARDS).
- Storage: replace the S3 service with local-disk storage (same upload/get/delete interface) under a configurable path.
- Port: ai_pipeline (agents, parser, report), assessment + share, candidate exam endpoints, question bank (questions/categories only), scoring, proctoring, version history, websocket for live monitoring.
- Drop: Level 1 users, workspaces, Google login, signup/register, `/auth` (replaced by SkillMate auth).
- Data: keep Level 1 services on the same Mongo (SkillMate's Motor client), collections prefixed `l1_` (`l1_questions`, `l1_assessments`, `l1_submissions`, ...) to avoid collisions; candidates are SkillMate `users` (role candidate). Workspace id removed.
- Extend SkillMate `EmailClient`: `SMTP_FROM`, per-candidate send, Brevo-compatible; reuse its Jinja templates style.
- Add tests (SkillMate has tests only for sourcing): port Level 1's pipeline/scoring/report tests.

**Phase 2 - Auth unification.**
- Level 1 admin endpoints use SkillMate `require_role(super_admin, interviewer)`; exam endpoints use `require_role(candidate)`.
- One user base for both levels (decision): Level 1 candidates are SkillMate `users` (role candidate) and use SkillMate's candidate login (email + access key). No temp passwords. Open point: SkillMate keys are single use; proposed default is a key reusable until the exam is completed, so reconnects work.

**Phase 3 - Flow (new code).**
- `hiring` record linking: sourcing JD -> selected profiles -> Level 1 run -> Level 2 interview -> results.
- Selecting a profile (existing `_promote`/`link_candidate`) triggers a Level 1 run for the selected profiles, using profile text + screening data instead of resume uploads and the profile's contact email.
- When a Level 1 result is final (all answers evaluated), compare with the pass mark setting: above 75% -> create the Level 2 interview through SkillMate's existing `assign`; below -> mark not advanced. Both outcomes recorded and emailed.
- Unified candidate timeline and results view.

**Phase 4 - Frontend port (Next.js 16 App Router, Tailwind v4 + shadcn, zustand).**
- Level 1 is React + Vite + Redux Toolkit + CSS modules: pages must be rewritten, not copied. Redux slices -> zustand stores; react-router -> App Router; CSS modules -> Tailwind/shadcn; `"use client"` for exam/proctoring.
- New routes: dashboard side (`/level1/...` questions, assessments, orchestrator run view, candidate review with expected essay answers + feedback), candidate exam (`(interview)` group: login via SkillMate, instructions, exam, completed).
- Touch points: `components/layout/sidebar.tsx`, `src/proxy.ts` `rolePaths`, `lib/constants.ts`, `lib/api/*`, `types/*`.
- Largest work: the exam page (~1,500 lines with MediaPipe/LiveKit proctoring hooks) and the assessment/share screens.

**Phase 5 - Infra.** Reuse `proxy/` unchanged (route table already covers /api, /livekit, frontend); backend port on this machine must be 8001 (VS Code holds 8000; frontend rewrite already defaults to 8001). Add `start_all.sh` (the existing `start_all.ps1` is Windows-only). Extension: only needs origin updates if hosts change.

**Phase 6 - Cleanup.** After the merged app passes verification: delete `level1-backend`, `level1-frontend` (asks you first), remove Talentia/level1 naming, update READMEs and the `.env.example`.

## Environment variables
**Reuse as is:** `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `CORS_ORIGINS`, `OPENAI_API_KEY`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET`.
**Same value, SkillMate's name:** `MONGODB_URL`->`MONGO_URI`, `DATABASE_NAME`->`MONGO_DB_NAME` (use `skill_mate`), `ACCESS_TOKEN_EXPIRE_MINUTES`->`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, `LIVEKIT_HOST`->`LIVEKIT_URL`, `FRONTEND_URL`->`APP_URL`, `APP_NAME`.
**Add to SkillMate settings:** `SMTP_FROM` (SkillMate only has a display name), `OPENAI_QUESTION_MODEL`, `OPENAI_ANALYSIS_MODEL`, `PIPELINE_CONCURRENCY`, `PIPELINE_MAX_FILE_MB`, `LEVEL1_PASS_PERCENT` (default 75, candidates must score above it). Files use local disk like SkillMate (decision), so no AWS keys.
**Needed from you (not in my env files):** `SUPER_ADMIN_EMAIL`, `SUPER_ADMIN_PASSWORD` (backend will not start without them), `ERP_BASE_URL` / `ERP_SECRET_KEY` for interviewer login, a running LiveKit server for Level 2 (and Level 1 live monitoring), `LIVEKIT_CLIENT_URL` if the browser URL differs.
**Drop:** `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `REFRESH_TOKEN_EXPIRE_DAYS`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_REGION`, `S3_BUCKET_NAME`, `VITE_*`.
Warning: same `JWT_SECRET_KEY` is fine once there is one backend; do not reuse it across separate deployments.

## Risks
- SkillMate has no frontend tests and backend tests only for sourcing: regressions are caught only by what we add.
- Beanie (SkillMate) vs plain Motor dicts (Level 1): keep Level 1 on Motor to avoid a rewrite; both share one Mongo.
- Single-use access keys vs an exam that must survive reconnects (proposed: reusable until exam completion).
- Auto-advance by pass mark: a wrong threshold advances or blocks real candidates; show it clearly in the UI and let admin override.
- Sourced profiles may have no resume file: Level 1's analysis input changes from resume text to profile text.
- Naukri extension: Terms-of-service/credit cost is outside this work; the extension stays as is.

## Verification
Backend `pytest` (SkillMate + ported Level 1); frontend `npm run lint` + `npm run build`; end-to-end on localhost: login -> JD -> sourcing -> select profiles -> Level 1 invite email -> candidate logs in with key -> exam -> evaluated report email -> automatic Level 2 assignment when above the pass mark.
