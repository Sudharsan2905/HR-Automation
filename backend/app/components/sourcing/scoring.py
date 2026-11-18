"""Deterministic candidate scoring (spec §5.3). The LLM reports evidence; this turns it into a number."""

from app.components.sourcing.models import SourcingRequirements
from app.components.sourcing.schemas import LLMScreenedProfile

BASE = 60
RELATED_PENALTY = 10
TOP_SKILL_EXCELLENT_BONUS = 25
TWO_STRONG_BONUS = 15
PREFERRED_BONUS = 7
TARGET_COMPANY_BONUS = 5
PROJECTS_BONUS = 5
LOCATION_BONUS = 3
SENIORITY_BONUS = 5

_STRONG = {"strong", "excellent"}


def _rejected(reason: str) -> tuple[int, dict]:
    return 0, {"rejected_reason": reason, "total": 0}


def compute_score(
    screen: LLMScreenedProfile,
    experience_years: float | None,
    ctc_lacs: float | None,
    req: SourcingRequirements,
) -> tuple[int, dict]:
    """Return (score 0..100, breakdown). Rejections score 0 with a reason."""
    # Line the screener's findings up with the requirement list by skill name (or variant),
    # so a skipped skill can't pass and the top skill is the JD's first, not the LLM's first.
    by_name = {f.skill.strip().lower(): f for f in screen.mandatory}
    ordered = []
    for spec in req.mandatory_skills:
        names = [spec.name, *spec.variants]
        f = next((by_name[n.strip().lower()] for n in names if n.strip().lower() in by_name), None)
        if f is None:
            return _rejected(f"not screened: {spec.name}")
        ordered.append(f)

    for f in ordered:
        if f.match == "absent":
            return _rejected(f"missing mandatory: {f.skill}")

    if experience_years is not None:
        too_junior = req.experience_min_years is not None and experience_years < req.experience_min_years
        too_senior = req.experience_max_years is not None and experience_years > req.experience_max_years
        if too_junior or too_senior:
            return _rejected("experience out of range")

    if ctc_lacs is not None and req.ctc_max_lacs is not None and ctc_lacs > req.ctc_max_lacs:
        return _rejected("CTC above budget")

    if screen.avoid_company_match:
        return _rejected("avoid-list company")

    related_penalty = -RELATED_PENALTY * sum(1 for f in ordered if f.match == "related")

    present = [f for f in ordered if f.match == "present"]
    first = ordered[0] if ordered else None
    if first is not None and first.match == "present" and first.strength == "excellent":
        strength_bonus = TOP_SKILL_EXCELLENT_BONUS
    elif sum(1 for f in present if f.strength in _STRONG) >= 2:
        strength_bonus = TWO_STRONG_BONUS
    else:
        strength_bonus = 0

    breakdown = {
        "rejected_reason": None,
        "base": BASE,
        "related_penalty": related_penalty,
        "strength_bonus": strength_bonus,
        "preferred_bonus": PREFERRED_BONUS * sum(1 for p in screen.preferred if p.present),
        "target_company": TARGET_COMPANY_BONUS if screen.target_company_match else 0,
        "projects": PROJECTS_BONUS if screen.relevant_projects else 0,
        "location": LOCATION_BONUS if screen.location_match else 0,
        "seniority": SENIORITY_BONUS if screen.seniority_match else 0,
    }
    raw = sum(v for k, v in breakdown.items() if k != "rejected_reason")
    total = max(0, min(100, raw))
    breakdown["total"] = total
    return total, breakdown


def related_notes(screen: LLMScreenedProfile) -> list[str]:
    return [
        f"{f.skill} not listed — related: {f.related_skill}"
        for f in screen.mandatory
        if f.match == "related"
    ]
