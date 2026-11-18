from app.components.jd_interview.schemas import LLMJdQuestion


def test_follow_ups_accept_strings_and_objects():
    q = LLMJdQuestion.model_validate({"question": "q?", "topic": "t", "follow_ups": ["a?", {"question": "b?"}]})
    assert [f.question for f in q.follow_ups] == ["a?", "b?"]
