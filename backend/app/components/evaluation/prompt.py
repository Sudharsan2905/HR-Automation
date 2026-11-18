EVALUATION_PROMPT = """You are evaluating a voice interview transcript. The transcript may contain dialogue in any language — always write your evaluation in English.

Participants:
- "Suvera AI": the AI interviewer asking questions
- "Candidate": the person being interviewed
- "Panel": a human panel member who may ask additional questions

=== CRITICAL: SEMANTIC RE-ATTRIBUTION ===
Voice interviews frequently produce temporal misalignment — a candidate may still be answering Q1 after Q2 has been asked, or may say the answer to Q2 after Q3 appears. DO NOT simply pair each candidate utterance with the preceding question.

Instead, follow this two-pass approach:
1. PASS 1 — Extract all questions: List every genuine interview question (from Suvera AI and Panel) in order.
2. PASS 2 — Attribute answers: For each question, find the candidate utterance(s) that SEMANTICALLY address it — even if those utterances appear after the next question was asked. Ask: "Does this utterance actually attempt to answer this question?" Use meaning, not position.

If a candidate's utterance is semantically answering a PREVIOUS question and not the current one, do NOT count it as an answer to the current question. Mark the current question as unanswered and score it 0.

=== INSTRUCTIONS ===
1. Extract every genuine interview question (Suvera AI utterances that are questions + Panel utterances that genuinely assess the candidate's knowledge/skill/experience).
2. For each question, identify the candidate response(s) that semantically address it using the two-pass approach above.
3. Write a BRIEF SUMMARY (1-3 sentences) of what the candidate said — do not copy verbatim transcript text. Summarize the substance of their response, even if it is wrong or off-topic. If they gave no relevant answer, state that clearly.
4. Score each answer 0-10 based on quality, correctness, and relevance to the specific question asked.
5. Write brief feedback in English explaining the score — specifically note if the candidate seemed to be answering a different question.
6. Provide an overall assessment, list of strengths, and list of areas for improvement.

Scoring:
- 10: Exceptional — all key points covered with depth and clarity
- 7-9: Good understanding, most key points covered
- 4-6: Partial understanding, notable gaps
- 1-3: Minimal understanding, mostly incorrect or irrelevant
- 0: No relevant response, unanswered, or candidate was addressing a different question

Return ONLY valid JSON with no additional text, matching this structure exactly:

=== EXPECTED OUTPUT FORMAT (JSON) ===
{{
  "evaluated_results": [
    {{
      "question": "What is the GIL in Python?",
      "asked_by": "ai",
      "answer": "The candidate mentioned having three years of experience, which did not address this question.",
      "feedback": "The candidate did not answer this question; their response appeared to address the previous introductory question instead.",
      "score": 0
    }},
    {{
      "question": "Explain your experience with FastAPI.",
      "asked_by": "panel",
      "answer": "The candidate described building REST APIs with FastAPI, mentioning dependency injection and async endpoints.",
      "feedback": "Solid understanding of FastAPI core concepts. Could have elaborated on middleware or background tasks.",
      "score": 7
    }}
  ],
  "overall_feedback": "2-3 sentence overall assessment of the candidate in English.",
  "strengths": ["strength 1", "strength 2"],
  "areas_for_improvement": ["area 1", "area 2"]
}}

=== INTERVIEW TRANSCRIPT ===

{transcript}"""
