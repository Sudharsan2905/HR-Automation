QUESTION_GENERATION_PROMPT = """You are a senior technical interviewer. Generate exactly {num_questions} interview questions based on the context below.

=== CONTEXT ===
{prompt_text}
{resume_section}
{existing_questions_section}
=== PARAMETERS ===
- Difficulty Level: {level}

=== RULES ===
1. Each question's "topic" MUST be 4 words or fewer (e.g., "Python Async", "Employee management", "Client Retention", "React Hooks").
2. "expected_points" array MUST have 1 to 4 items — each a concise point the candidate should cover. At least one point is mandatory.
3. "follow_ups" — include 1-2 follow-up questions if needed. Follow-ups should probe deeper (e.g., edge cases, trade-offs, real-world application). 
                  Use an empty array for straightforward questions that need no drill-down. Max 2 items.
4. Questions should match the difficulty level:
   - easy: fundamentals, definitions, basic usage
   - medium: applied knowledge, trade-offs, real-world scenarios
   - pro: architecture, edge cases, deep internals, system design
5. Cover diverse topics — don't cluster on one technology.
6. Extract relevant tags/keywords from the context as a string array (e.g., ["Python", "FastAPI", "MongoDB", "Docker"]).
7. Do NOT repeat or rephrase any question from the EXISTING QUESTIONS section. Each new question must be distinct in topic or angle.

=== RESPONSE FORMAT (strict JSON) ===
{{
  "tags": ["skill1", "skill2", ...],
  "questions": [
    {{
      "question": "Your interview question here?",
      "topic": "Short Topic",
      "expected_points": ["point 1", "point 2", "point 3"],
      "follow_ups": [
        {{"question": "Follow-up question 1?"}},
        {{"question": "Follow-up question 2?"}}
      ]
    }}
  ]
}}

Return ONLY valid JSON. No markdown, no explanations."""


SINGLE_QUESTION_PROMPT = """You are a senior interviewer specializing in {domain} — {domain_title}.

=== USER REQUEST ===
{user_prompt}

=== CONSTRAINTS ===
- Domain: {domain} / {domain_title}
- Tags: {tags}
- Difficulty: {difficulty}

=== STRICT RULES ===
1. Generate EXACTLY ONE interview question that is directly relevant to the domain and tags above.
2. "topic" — 4 words max (e.g., "React State Management").
3. "expected_points" — 1 to 4 concise points the candidate should cover. At least one point is mandatory.
4. "follow_ups" — optional, include ONLY when the question genuinely benefits from deeper probing. Use an empty array if the question is self-contained. Max 2 items when included.
5. Keep the question between 1-3 sentences. Be specific, not vague.

=== RESPONSE FORMAT (strict JSON) ===
{{
  "question": "Your interview question here?",
  "topic": "Short Topic",
  "expected_points": ["point 1", "point 2", "point 3"],
  "follow_ups": [
    {{"question": "Follow-up question 1?"}}
  ]
}}

Return ONLY valid JSON. No markdown, no explanations."""
