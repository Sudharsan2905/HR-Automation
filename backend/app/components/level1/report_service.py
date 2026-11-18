"""Pure helpers that render a candidate's result report (no email is sent here)."""

import html

from app._core.settings import settings


def unevaluated_count(sub: dict) -> int:
    """Questions with no definite correct/incorrect result (e.g. essay scoring failed)."""
    count = 0
    for rd in sub.get("rounds_data", []):
        results = rd.get("question_results") or {}
        for q in rd.get("questions", []):
            if (results.get(q.get("id")) or {}).get("is_correct") is None:
                count += 1
    return count


def _result_label(res: dict | None) -> str:
    return "Correct" if res and res.get("is_correct") else "Incorrect"


def _row(index: int, q: dict, res: dict | None) -> str:
    fb = html.escape((res or {}).get("feedback") or "")
    text = html.escape((q.get("text") or "")[:300])
    note = f"<br/><i style=color:#64748b>{fb}</i>" if fb else ""
    return (
        f"<tr><td style='padding:6px;border-bottom:1px solid #e2e8f0'>{index}. {text}{note}</td>"
        f"<td style='padding:6px;border-bottom:1px solid #e2e8f0;white-space:nowrap'>"
        f"{_result_label(res)}</td></tr>"
    )


def build_report_html(jd_title: str, name: str, sub: dict) -> str:
    """Render the result report HTML for one submission."""
    rows = []
    for rd in sub.get("rounds_data", []):
        results = rd.get("question_results") or {}
        rows += [_row(i, q, results.get(q.get("id"))) for i, q in enumerate(rd.get("questions", []), 1)]
    note = ""
    if sub.get("status") in ("terminated", "malpractice"):
        note = "<p style='color:#b91c1c'>Your exam was ended early due to a proctoring violation.</p>"
    return (
        "<div style='font-family:Inter,Arial,sans-serif;max-width:640px;margin:0 auto;padding:24px'>"
        f"<h2 style='color:#2563EB'>{html.escape(settings.APP_NAME)}: Assessment Report</h2>"
        f"<p>Hello {html.escape(name)}, here is your result for <b>{html.escape(jd_title)}</b>.</p>"
        f"<p style='font-size:18px'>Score: <b>{sub.get('score', 0)}</b> &middot; "
        f"<b>{sub.get('percentage', 0)}%</b></p>{note}"
        f"<table style='width:100%;border-collapse:collapse;font-size:14px'>{''.join(rows)}</table>"
        "</div>"
    )
