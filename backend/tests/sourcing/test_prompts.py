from app.components.sourcing.prompt import JD_ANALYST_PROMPT, SCREENER_PROMPT, SEARCH_STRATEGIST_PROMPT


def test_every_prompt_mentions_json():
    # OpenAI's json_object response format rejects requests whose messages never say "json".
    rendered = [
        JD_ANALYST_PROMPT.format(jd_text="Python developer"),
        SEARCH_STRATEGIST_PROMPT.format(requirements_json="{}"),
        SCREENER_PROMPT.format(requirements_json="{}", profiles_json="[]"),
    ]
    for text in rendered:
        assert "json" in text.lower()


def _fields(model) -> set[str]:
    return set(model.model_fields)


def test_prompts_spell_out_the_exact_output_shape():
    # The LLM client sends only response_format=json_object, never the schema, so each prompt
    # must show every key — otherwise a renamed key silently becomes an empty default.
    from app.components.sourcing.schemas import (
        LLMPreferredFinding, LLMRequirements, LLMScreenBatch, LLMScreenedProfile, LLMSearchPlan, LLMSkill, LLMSkillFinding,
    )
    cases = [
        (JD_ANALYST_PROMPT.format(jd_text="x"), [LLMRequirements, LLMSkill]),
        (SEARCH_STRATEGIST_PROMPT.format(requirements_json="{}"), [LLMSearchPlan]),
        (SCREENER_PROMPT.format(requirements_json="{}", profiles_json="[]"),
         [LLMScreenBatch, LLMScreenedProfile, LLMSkillFinding, LLMPreferredFinding]),
    ]
    for text, models in cases:
        assert "OUTPUT FORMAT" in text
        template = text.split("OUTPUT FORMAT", 1)[1]
        for m in models:
            for field in _fields(m):
                assert f'"{field}"' in template, f"{m.__name__}.{field} missing from output template"
