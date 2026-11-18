# AI Hiring Pipeline - HTTP API contract (Level 1 backend)

Base URL (local): `http://localhost:8002`. All paths are under `/api/pipelines`.
Auth: `Authorization: Bearer <access_token>` from `POST /api/auth/admin/login`
(role `admin` or `super_admin`; an `admin` can only use workspaces in his `workspace_ids`).
All JSON responses use the app-wide envelope: `{ "success": bool, "message": str, "data": ... }`
(errors: `{ "success": false, "message": str, "data": null, "detail": str }`). Everything below
describes the `data` field.

Pipeline status: `queued | running | done | done_with_errors | failed`.
Step keys (fixed order): `intake`, `analysis`, `questions`, `assessment`, `provisioning`, `invites`.
Step status: `pending | running | done | failed | skipped`.
Poll `GET /api/pipelines/{id}` every 1-2 s while `status` is `queued|running` (steps + `events` are live).

## 1. Create - `POST /api/pipelines`  (multipart/form-data)

| field | type | notes |
|---|---|---|
| `jd_title` | string | required |
| `jd_text` | string | required (>= 20 chars) |
| `workspace_id` | string | required, ObjectId of a workspace the admin can access |
| `candidates` | string (JSON list) | required, 1..50 items, each `{ "name"?: string, "email"?: string, "phone"?: string, "description": string }` |
| `resume_{i}` | file | PDF or DOCX for `candidates[i]` (i = 0-based). Max `PIPELINE_MAX_FILE_MB` (default 5) |
| `photo_{i}` | file | jpg/png/webp for `candidates[i]` (optional) |

Each candidate needs a resume or a non-empty description. Email is resolved from the resume text first, then from
`description`, then from the optional `email` field. No email => candidate gets status `needs_email`, no invite is sent.

Response `201`: `{ "success": true, "message": "...", "data": { "id": "<pipeline_id>", "status": "queued" } }`
The run continues in the background; poll the detail endpoint.

## 2. List - `GET /api/pipelines?workspace_id=&page=1&page_size=20`

`data`:
```json
{ "pipelines": [ { "id", "workspace_id", "jd_title", "status", "error", "failed_step",
                   "assessment_id", "share_link", "steps": [ ...as in detail... ],
                   "counts": { ... as in detail ... }, "created_at", "updated_at" } ],
  "pagination": { "total", "page", "page_size", "total_pages", "has_next", "has_prev" } }
```
`workspace_id` optional filter (non super admins only ever see their own workspaces).

## 3. Detail - `GET /api/pipelines/{id}`

```json
{
  "id": "...", "workspace_id": "...", "jd_title": "Senior Python Engineer",
  "status": "running", "error": null, "failed_step": null,
  "category_id": "...|null", "assessment_id": "...|null",
  "share_id": "...|null", "share_link": "...|null",
  "exam_url": "http://localhost:5173/assessment/<share_link>|null",
  "question_config": { "counts": { "mcq_single": 10, "mcq_multi": 6, "essay": 4 }, "duration_minutes": 60 },
  "steps": [ { "key": "intake", "agent": "Profile Intake Agent", "title": "...", "description": "...",
               "status": "done", "started_at": "ISO|null", "finished_at": "ISO|null",
               "progress": { "done": 2, "total": 2 }, "detail": "2/2 parsed",
               "error": null } ],
  "events": [ { "ts": "ISO", "step": "analysis", "level": "info|warn|error", "message": "..." } ],
  "counts": { "total": 2, "needs_email": 0, "analyzed": 2, "invited": 2, "invite_failed": 0,
              "submitted": 0, "report_sent": 0, "report_failed": 0, "failed": 0 },
  "candidates": [ {
      "id": "...", "name": "...", "email": "x@y.com|null", "email_source": "resume|description|input|null",
      "description": "...", "has_resume": true, "has_photo": true, "resume_filename": "cv.docx",
      "status": "queued|parsed|analyzed|needs_email|provisioned|invited|failed",
      "analysis": { "name", "match_score", "matched_skills": [], "missing_skills": [], "experience_years",
                    "strengths": [], "gaps": [], "focus_topics": [], "suitable": true, "summary": "..." } ,
      "user_id": "...|null", "submission_id": "...|null",
      "invite_status": "pending|sent|failed|skipped", "invite_error": "detailed error|null", "invited_at": "ISO|null",
      "exam_status": "pending|in_progress|completed|...|null", "score": 0, "percentage": 0.0,
      "report_status": "pending|sent|failed", "report_sent_at": "ISO|null", "report_error": "...|null",
      "error": "...|null", "failed_step": "...|null" } ],
  "created_by": "...", "created_at": "ISO", "updated_at": "ISO"
}
```
`analysis` is `null` until the analysis step handled that candidate. `invite_status` is `skipped` for `needs_email`.
`report_status` stays `pending` until the exam is submitted AND every answer (incl. essays) is evaluated; then exactly
one report email is sent (candidate, admin in Cc) and it becomes `sent` (guarded by `report_sent_at`), or `failed`.

## 4. Questions - `GET /api/pipelines/{id}/questions`

`data`: `{ "counts": {"mcq_single":10,"mcq_multi":6,"essay":4,"total":20}, "questions": [ { "id", "question_text",
"question_type": "mcq_single|mcq_multi|essay", "complexity", "options": [ {"id","text","is_correct"} ] ([] for essay),
"correct_answer": "model answer (essays) | null" } ] }`. Empty list until the `assessment` step is done.

## 5. Resend invites

* `POST /api/pipelines/{id}/invites/resend` - all candidates with an email whose invite is not `sent`
  (a fresh temporary password is issued for each). Body: none. `data`: `{ "invited": n, "failed": n }`.
* `POST /api/pipelines/{id}/candidates/{candidate_id}/invite/resend` - one candidate, **even if already sent**
  (new temporary password). Same response.

## 6. Re-run a failed step - `POST /api/pipelines/{id}/retry`

Body (JSON, optional): `{ "step": "analysis" }`. Defaults to the pipeline's `failed_step`. The run restarts from
that step onwards, reusing earlier results. `409` if the pipeline is already running. Response `data`: `{ "id", "status": "running", "step": "..." }`.

## 7. Report resend - `POST /api/pipelines/{id}/candidates/{candidate_id}/report/resend`

Only when the candidate is fully evaluated; re-sends the (single) result report. `data`: `{ "sent": true }`.

## 8. Files

`GET /api/pipelines/{id}/candidates/{candidate_id}/resume` and `.../photo` return the stored file (admin auth).

## Emails (backend side effects)

* Invite: ONE email per candidate containing username (their email), temporary password and the exam link
  `FRONTEND_URL/assessment/<share_link>` (candidates log in at the exam link with those credentials).
* Report: ONE email after full evaluation, To = candidate, Cc = the admin who created the pipeline.
