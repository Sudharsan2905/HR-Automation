"""The three sourcing agents. Each is one structured LLM call, like the rest of SkillMate."""

import asyncio
import json
import re

from app._core.settings import settings
from app.components.sourcing.models import SkillSpec, SourcedProfile, SourcingRequirements, SourcingSearchPlan
from app.components.sourcing.prompt import JD_ANALYST_PROMPT, SCREENER_PROMPT, SEARCH_STRATEGIST_PROMPT
from app.components.sourcing.schemas import LLMRequirements, LLMScreenBatch, LLMScreenedProfile, LLMSearchPlan
from app.components.utils.llm_client import get_llm_client
from app.components.utils.logger import log

TEMPERATURE = 0.2
MAX_MANDATORY = 10
MAX_PREFERRED = 8
MAX_VARIANTS = 6
MAX_COMPANIES = 20
# A Boolean search ANDs its skill groups, so every extra group shrinks the result: past a handful it returns nobody.
# Candidates are searched on the most central mandatory skills; screening still checks all of them.
SEARCH_MAX_SKILLS = 5

# Soft skills and personal traits can't be searched for or screened (and "Communication skills" in quotes matches
# almost no profile): the prompt forbids them, and this removes any the model lists anyway.
_SOFT_SKILL = re.compile(
    r"^(?:(?:good|strong|excellent|effective)\s+)?(?:(?:verbal|written|oral|interpersonal)\s+)?communication(?:\s+skills?)?$"
    r"|^(?:good\s+)?problem[\s-]*solving(?:\s+(?:skills?|abilit(?:y|ies)))?$"
    r"|^(?:team[\s-]*work|team\s+player|collaboration|collaborative|leadership|interpersonal\s+skills?"
    r"|critical\s+thinking|analytical\s+(?:thinking|skills?)|time\s+management|adaptability|work\s+ethic"
    r"|self[\s-]*motivat(?:ed|ion)|attention\s+to\s+detail|creativity|ownership|fast\s+learner|ability\s+to\s+learn"
    r"|decision[\s-]*making|presentation\s+skills?)$",
    re.IGNORECASE,
)


def _is_soft_skill(name: str) -> bool:
    return bool(_SOFT_SKILL.match(re.sub(r"\s+", " ", (name or "").strip(" .,;:-"))))

# Profile fields the screener sees (raw scraped extras are left out to keep prompts small)
_SCREEN_FIELDS = (
    "source_link", "source", "name", "headline", "snippet", "location", "current_company", "current_title",
    "skills", "experiences", "education", "total_experience", "experience_years", "current_ctc_lacs",
)


def _skills(items, limit: int) -> list[SkillSpec]:
    out = []
    for s in items:
        name = (s.name or "").strip()
        if not name or _is_soft_skill(name):
            continue
        variants = [v.strip() for v in s.variants if v and v.strip()][:MAX_VARIANTS]
        out.append(SkillSpec(name=name, variants=variants))
        if len(out) == limit:
            break
    return out


def _clean(items: list[str], limit: int) -> list[str]:
    return [i.strip() for i in items if i and i.strip()][:limit]


async def _call(prompt: str, schema):
    return await get_llm_client().generate_structured(
        prompt, schema, max_tokens=settings.LLM_MAX_TOKENS_SOURCING, temperature=TEMPERATURE,
    )


async def analyze_jd(jd_text: str) -> SourcingRequirements:
    """Agent 1 — JD Analyst."""
    r: LLMRequirements = await _call(JD_ANALYST_PROMPT.format(jd_text=jd_text), LLMRequirements)
    if not r.is_valid_jd:
        raise ValueError(r.invalid_reason or "This does not look like a job description")
    mandatory = _skills(r.mandatory_skills, MAX_MANDATORY)
    if not mandatory:
        # Nothing to search or screen on: say so now, instead of failing later with an empty search.
        raise ValueError(
            "This text does not list any required skills, so there is nothing to search candidates on. "
            "Delete this JD and create it again with the full job description (the duties and the skills required)."
        )
    return SourcingRequirements(
        role_title=(r.role_title or "").strip(),
        experience_min_years=r.experience_min_years,
        experience_max_years=r.experience_max_years,
        ctc_max_lacs=r.ctc_max_lacs,
        locations=_clean(r.locations, MAX_COMPANIES),
        mandatory_skills=mandatory,
        preferred_skills=_skills(r.preferred_skills, MAX_PREFERRED),
        target_companies=_clean(r.target_companies, MAX_COMPANIES),
        avoid_companies=_clean(r.avoid_companies, MAX_COMPANIES),
    )


async def build_search_plan(req: SourcingRequirements) -> SourcingSearchPlan:
    """Agent 2 — Search Strategist. The LLM writes the keyword strings; filters are copied in code."""
    core = req.model_copy(update={"mandatory_skills": req.mandatory_skills[:SEARCH_MAX_SKILLS]})
    prompt = SEARCH_STRATEGIST_PROMPT.format(requirements_json=core.model_dump_json(indent=2))
    p: LLMSearchPlan = await _call(prompt, LLMSearchPlan)
    primary = " ".join((p.primary_keywords or "").split())
    narrowed = " ".join((p.narrowed_keywords or "").split()) or primary
    return SourcingSearchPlan(
        primary_keywords=primary,
        narrowed_keywords=narrowed,
        experience_min=req.experience_min_years,
        experience_max=req.experience_max_years,
        locations=list(req.locations),
        ctc_max_lacs=req.ctc_max_lacs,
    )


async def screen_profiles(req: SourcingRequirements, profiles: list[SourcedProfile]) -> dict[str, LLMScreenedProfile]:
    """Agent 3 — Candidate Screener. Returns findings keyed by source_link; unknown links are dropped.

    Profiles go in chunks of SOURCING_SCREEN_CHUNK, up to SOURCING_SCREEN_CONCURRENCY calls at once."""
    chunk = max(1, settings.SOURCING_SCREEN_CHUNK)
    gate = asyncio.Semaphore(max(1, settings.SOURCING_SCREEN_CONCURRENCY))
    req_json = req.model_dump_json(indent=2)

    async def one(n: int, batch: list[SourcedProfile]) -> list[LLMScreenedProfile]:
        wanted = {p.source_link for p in batch}
        payload = [{k: getattr(p, k) for k in _SCREEN_FIELDS} for p in batch]
        prompt = SCREENER_PROMPT.format(requirements_json=req_json, profiles_json=json.dumps(payload, default=str))
        async with gate:
            try:
                result: LLMScreenBatch = await _call(prompt, LLMScreenBatch)
            except Exception as e:  # this chunk's profiles come back unscreened; the rest still count
                log.warning("Screening chunk %d failed: %s", n, e)
                return []
        return [s for s in result.profiles if s.source_link in wanted]

    batches = [profiles[i:i + chunk] for i in range(0, len(profiles), chunk)]
    out: dict[str, LLMScreenedProfile] = {}
    for found in await asyncio.gather(*(one(n + 1, b) for n, b in enumerate(batches))):
        for s in found:
            out.setdefault(s.source_link, s)
    return out
