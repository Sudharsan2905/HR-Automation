import re

from app._core.settings import settings
from app.components.auth.models import User
from app.components.common.schemas import InterviewStatus, Role
from app.components.evaluation.models import EvaluationResult, QuestionEvaluation
from app.components.evaluation.prompt import EVALUATION_PROMPT
from app.components.evaluation.schemas import LLMTranscriptEvaluation
from app.components.interview.models import Interview
from app.components.question_set.models import QuestionSet
from app.components.session.transcript import Transcript
from app.components.utils.llm_client import get_llm_client
from app.components.utils.logger import log


async def run_evaluation(interview_id: str):
    """Evaluate interview from transcript — single LLM call."""
    try:
        interview = await Interview.get(interview_id)
        if not interview:
            log.error("Evaluation failed: interview %s not found", interview_id)
            return

        qs = await QuestionSet.get(interview.question_set_id)
        if not qs:
            log.error("Evaluation failed: question set %s not found", interview.question_set_id)
            return

        transcripts = await Transcript.find(
            Transcript.interview_id == interview_id
        ).sort("+timestamp").to_list()

        if not transcripts:
            log.error("Evaluation failed: no transcripts for interview %s", interview_id)
            return

        candidate = await User.find_one(User.email == interview.candidate_mail)
        candidate_name = candidate.full_name if candidate and candidate.full_name else "Candidate"
        interviewer = await User.get(interview.interviewer_id)
        interviewer_name = interviewer.full_name if interviewer and interviewer.full_name else "Panel"

        # Build transcript string
        lines = []
        for t in transcripts:
            role_label = {"ai": "Suvera AI", "candidate": "Candidate", "interviewer": "Panel"}.get(t.role, t.role)
            lines.append(f"[{t.timestamp.strftime('%H:%M:%S')}] {role_label}: {t.text}")

        transcript_text = "\n".join(lines)
        prompt = EVALUATION_PROMPT.format(transcript=transcript_text)

        llm = get_llm_client()
        result = await llm.generate_structured(prompt, LLMTranscriptEvaluation, max_tokens=settings.LLM_MAX_TOKENS_EVALUATION)

        evaluated_results = [
            QuestionEvaluation(
                question=qe.question,
                asked_by=qe.asked_by,
                answer=qe.answer,
                feedback=qe.feedback,
                score=qe.score,
            )
            for qe in result.evaluated_results
        ]

        total_score = sum(qe.score for qe in evaluated_results)
        # max_score based on number of exchanges LLM identified, not the question set count
        max_score = len(evaluated_results) * 10.0 if evaluated_results else 10.0
        percentage = min(total_score / max_score * 100, 100.0) if max_score > 0 else 0

        is_partial = interview.status == InterviewStatus.PARTIALLY_COMPLETED

        evaluation = EvaluationResult(
            interview_id=interview_id,
            candidate_mail=interview.candidate_mail,
            interviewer_id=interview.interviewer_id,
            candidate_name=candidate_name,
            total_score=total_score,
            max_score=max_score,
            percentage=percentage,
            is_partial=is_partial,
            evaluated_results=evaluated_results,
            overall_feedback=result.overall_feedback,
            strengths=result.strengths,
            areas_for_improvement=result.areas_for_improvement,
        )
        await evaluation.insert()

        # Generate both PDFs
        pdf_paths = []
        interview_date = evaluation.evaluated_at.strftime("%B %d, %Y")
        domain_label = f"{qs.domain.replace('_', ' ').title()} / {qs.domain_title.replace('_', ' ').title()}"

        try:
            from app.components.utils.pdf_generator import generate_conversation_pdf, generate_report_pdf

            conversation_pdf = await generate_conversation_pdf(
                interview_id=interview_id,
                candidate_name=candidate_name,
                interview_date=interview_date,
                domain=qs.domain,
                domain_title=qs.domain_title,
                transcripts=transcripts,
            )
            pdf_paths.append(conversation_pdf)
            evaluation.conversation_pdf_path = conversation_pdf

            insights_pdf = await generate_report_pdf(evaluation, qs)
            pdf_paths.append(insights_pdf)
            evaluation.pdf_report_path = insights_pdf

            await evaluation.save()
        except Exception as e:
            log.warning("PDF generation failed: %s", e)

        # Send emails to both candidate and interviewer
        try:
            from app.components.utils.email_client import get_email_client

            email_client = get_email_client()
            if email_client and pdf_paths:
                score_str = f"{total_score:.1f}"
                max_score_str = f"{max_score:.0f}"
                pct_str = f"{percentage:.1f}"

                # Email to candidate
                await email_client.send_interview_results(
                    to=interview.candidate_mail,
                    recipient_name=candidate_name,
                    candidate_name=candidate_name,
                    interview_date=interview_date,
                    score=score_str,
                    max_score=max_score_str,
                    percentage=pct_str,
                    domain=domain_label,
                    intro_text="Your mock interview has been evaluated. Please find the detailed results and transcript attached.",
                    pdf_paths=pdf_paths,
                )

                # Email to interviewer
                if interviewer and interviewer.email:
                    await email_client.send_interview_results(
                        to=interviewer.email,
                        recipient_name=interviewer_name,
                        candidate_name=candidate_name,
                        interview_date=interview_date,
                        score=score_str,
                        max_score=max_score_str,
                        percentage=pct_str,
                        domain=domain_label,
                        intro_text=f"The mock interview for {candidate_name} has been completed and evaluated. Please find the detailed results and transcript attached.",
                        pdf_paths=pdf_paths,
                    )
        except Exception as e:
            log.warning("Failed to send interview result emails: %s", e)

        log.info("Evaluation complete: interview=%s, score=%.1f/%s, pct=%.1f%%", interview_id, total_score, max_score, percentage)

    except Exception as e:
        log.error("Evaluation failed for interview %s: %s", interview_id, e, exc_info=True)


async def get_evaluation(interview_id: str) -> EvaluationResult | None:
    """Fetch evaluation by interview ID."""
    return await EvaluationResult.find_one(EvaluationResult.interview_id == interview_id)


async def get_evaluations_by_interviewer(
    interviewer_id: str,
    skip: int = 0,
    limit: int = 100,
    candidate_search: str | None = None,
    max_percentage: float | None = None,
) -> dict:
    """Fetch paginated evaluations for interviews created by this interviewer."""
    mongo_filter: dict = {"interviewer_id": interviewer_id}

    if candidate_search:
        escaped = re.escape(candidate_search)
        matched = await User.find({
            "role": Role.CANDIDATE.value,
            "$or": [
                {"full_name": {"$regex": escaped, "$options": "i"}},
                {"email": {"$regex": escaped, "$options": "i"}},
            ],
        }).to_list()
        emails = [u.email for u in matched]
        if not emails:
            return {"total": 0, "items": []}
        mongo_filter["candidate_mail"] = {"$in": emails}

    if max_percentage is not None:
        mongo_filter["percentage"] = {"$lte": max_percentage}

    total = await EvaluationResult.find(mongo_filter).count()
    evals = await EvaluationResult.find(mongo_filter).sort("-evaluated_at").skip(skip).limit(limit).to_list()
    return {"total": total, "items": [_eval_to_summary(e) for e in evals]}


def _eval_to_summary(e: EvaluationResult) -> dict:
    return {
        "id": str(e.id),
        "interview_id": e.interview_id,
        "candidate_mail": e.candidate_mail,
        "candidate_name": e.candidate_name,
        "total_score": e.total_score,
        "max_score": e.max_score,
        "percentage": e.percentage,
        "is_partial": e.is_partial,
        "evaluated_at": e.evaluated_at.isoformat(),
        "has_pdf": e.pdf_report_path is not None,
        "has_transcript_pdf": e.conversation_pdf_path is not None,
    }
