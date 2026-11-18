# Development Standards

This document defines the coding standards, expectations, and non-negotiable rules for this project. Every contributor, human or AI agent, must follow these without exception.

---

## Core Philosophy

Write production-grade code from the start. No temporary fixes. No "we'll clean it up later." If it's not ready for production, it doesn't get merged.

Every configurable value must be exposed to the UI. If an admin needs to type a magic string they can't discover through the interface, the feature is incomplete. The backend must always provide discovery endpoints for any value the frontend needs to select from.

---

## Code Quality

### Cognitive Load

Code must be easy to read and reason about. Low cognitive complexity is mandatory — this will be verified with SonarQube. If a function needs a flowchart to understand, it needs to be rewritten.

- Flat is better than nested. Prefer early returns over deep if-else chains.
- One function does one thing. If you're naming it `process_and_validate_and_save`, it's doing too much.
- No clever tricks. Readable beats smart every time.

### Docstrings

Single line only. If the function name and signature don't explain it well enough, the function is poorly designed.

```python
# Good
"""Check if user has exceeded rate limits."""

# Bad — never do this
"""
Check if the user has exceeded the configured rate limits
for the specified category by querying Redis sorted sets
and comparing against the admin-configured window limits.

Args:
    user_id: The unique identifier of the user
    category: The rate limit category to check
    ...
"""
```

### Comments

Only where the logic isn't self-evident. Don't narrate what the code already says.

```python
# Bad
user = get_user()  # Get the user

# Good — explains WHY, not WHAT
# Redis returns None for both expired and non-existent keys
if user_data is None:
```

---

## API Design

### Every API Must Be Production-Complete

An API endpoint is not done until:

- It has proper authentication and authorization (no open admin routes).
- Validation catches invalid input at the boundary and returns a clear error message.
- Errors follow the standard response structure — no raw exceptions leaking to the client.
- Any value the frontend needs to select from is available via a discovery GET endpoint.

### Standard Response Structure

Every response, success or failure, must follow the same format. No exceptions. If a Pydantic validation error, a 500, or any other failure bypasses this structure, it's a bug.

### Auto-Discovery Over Hardcoded Values

If the backend defines a set of valid values (API categories, platforms, countries, roles), expose them via a GET endpoint. The frontend should never hardcode lists that originate from the backend.

FastAPI provides `app.routes` at runtime — use it. Don't maintain manual enums for things the framework already knows.

### Validation

Validate at the boundary. Use Pydantic models and validators to enforce business rules (like `minute <= hour <= day <= week`). Don't scatter validation logic across services and routes.

---

## Security

### Authentication Is Not Optional

Every admin route must be protected from day one. Not after someone notices. Not before prod push. From the first commit.

Router-level dependencies are preferred over per-endpoint decorators for admin routes — one line protects all endpoints.

### No Dev Bypasses in Main Branch

Dev bypasses (hardcoded users, fake tokens, disabled auth) must never exist in the main branch. If they're needed for local development, they must be behind an explicit environment flag and clearly marked with `# TODO: Remove this dev bypass` so they're searchable.

---

## Error Handling

### Global Over Local

Handle exception types globally in the exception handler, not with try-except in every route. If a new exception type isn't caught by the global handler, add it there — don't patch individual routes.

### No Silent Failures

If something fails, the user must know. The frontend must always receive a structured error response with a clear message. A 500 with no body or a response that doesn't match the expected structure is unacceptable.

---

## Architecture Decisions

### Automatic Over Manual

If the framework can provide information automatically (registered routes, available models, enum values), use that instead of maintaining a manual list. Manual lists drift from reality. Automation doesn't.

### Single Source of Truth

Every piece of configuration, every enum, every set of valid values — defined once, used everywhere. If you find yourself typing the same string in two places, one of them should be a reference to the other.

### Let the Database Do the Work

Never load entire collections into Python memory to count, filter, or aggregate. If MongoDB (or any database) can do it in a query or aggregation pipeline, it must be done there. Python loops over database results are a performance liability that gets worse with scale.

- **MongoDB**: Use aggregation pipelines (`$group`, `$match`, `$sum`, `$avg`) for statistics, counts, and grouping.
- **RDBMS (PostgreSQL, MySQL, etc.)**: Use SQL `GROUP BY`, `COUNT`, `SUM`, `AVG`, `HAVING`, and window functions. If using an ORM like SQLAlchemy, use `.group_by()`, `func.count()`, `func.sum()` — not `query.all()` followed by a Python loop.
- Use database-level filters instead of fetching all rows/documents and filtering in Python.
- The only acceptable Python-side processing is for transformations the database genuinely cannot perform.

### Decorators and Middleware Must Respect Execution Order

If a decorator needs data that's set inside the function body (like `request.state.user_id`), it will never work — the decorator runs first. Always verify the execution order when combining decorators with dependency injection.

---

## What Not To Do

- Don't propose temporary fixes. Find the proper solution.
- Don't add features without exposing their configuration to the UI.
- Don't leave admin endpoints unprotected and plan to "add auth later."
- Don't return raw framework errors to the client. Wrap everything.
- Don't maintain manual lists of things the framework already knows.
- Don't write multi-line docstrings. One line or none.
- Don't add unnecessary abstractions, type annotations, or comments to code you didn't change.
- Don't pad responses with filler text. Be direct and concise.
- Don't suggest the inferior approach first and wait to be corrected. Lead with the best solution.

---

## For AI Coding Agents

- Lead with the most efficient, production-grade solution. Not the simplest to explain — the best to ship.
- If there's an automatic way and a manual way, always choose automatic.
- Don't generate walls of text explaining what you're about to do. Do it.
- When you spot a pattern issue (like missing auth on routes), flag all instances — not just the one being discussed.
- If you make a mistake, own it, fix it, move on. No filler apologies.
- Treat every change as if it's going to production today.