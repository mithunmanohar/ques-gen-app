# Question Set Studio — Functional & Data Spec

This document describes what the app does, the data it manages, and the
contracts between its pieces — so both the person extending the code and
the person just configuring/using it have one place to check "how is this
supposed to work."

## 1. Goal

Turn CBSE past-year question papers into fresh, exam-pattern-matched
practice sets, and grade a child's handwritten attempt at one — all running
locally, with DeepSeek as the only external dependency.

## 2. Roles (informal — there's no login/auth in this app)

- **Admin/parent**: uploads past papers, defines patterns, generates
  question sets, reviews graded results.
- **Student (child)**: solves a printed question set on paper; doesn't use
  the app directly except to have their photographed answer sheet uploaded
  on their behalf.

## 3. The three-stage flow

```
 Admin page                Generate page              Submit & Evaluate page
┌────────────────┐        ┌─────────────────┐        ┌───────────────────────┐
│ Upload past     │        │ Pick a Pattern   │        │ Print a Question Set   │
│ papers (PDF/MD) │──text─▶│ + source docs    │──────▶ │ → child solves on paper│
│                 │        │ → DeepSeek       │  Q's   │ → photograph it        │
│ Define Patterns │        │   generates a    │        │ → DeepSeek vision grades│
│ (exam blueprint)│──spec─▶│   Question Set   │        │   it against the hidden│
└────────────────┘        └─────────────────┘        │   answer key            │
                                                        └───────────────────────┘
```

## 4. Core concepts & data model

| Entity | What it is |
|---|---|
| **SourceDocument** | An uploaded past-year paper (or notes). Stores the original file plus extracted plain text. Used only as reference material fed into the generation prompt — never shown to the student, never copied verbatim by design instruction to the model. |
| **Pattern** | The exam blueprint / "spec": subject, grade, sections, and per-section question type + count + marks. Validated against [`config/pattern.schema.json`](config/pattern.schema.json). This is the main lever for controlling what generated papers look like. |
| **QuestionSet** | One generated paper: a list of `Question`s produced from a `Pattern` (+ optional `SourceDocument`s) by DeepSeek. Has a status (`generating`/`ready`/`failed`). |
| **Question** | A single question: section, type (MCQ/VSA/SA/LA/CASE_STUDY), text, options (MCQ only), marks, difficulty, and a **hidden** `expected_answer` + `rubric` used only for grading. |
| **Submission** | One attempt: a child's photographed answer sheet(s) against a specific `QuestionSet`. |
| **Evaluation** | The graded result of a `Submission`: total marks, overall feedback, and one `EvaluationItem` per question (extracted answer, marks awarded, correctness, feedback). |

Full field-level detail is in `backend/app/models.py`, which is the source
of truth; this doc describes intent, not every column.

## 5. The Pattern spec (`config/pattern.schema.json`)

A Pattern is deliberately generic — not tied to one subject or grade — so
the same mechanism covers any CBSE subject/class. Shape:

```jsonc
{
  "name": "CBSE Class 10 Science - Sample Paper Pattern",
  "subject": "Science",
  "grade": "10",
  "total_marks": 49,               // informational; not enforced against sections
  "duration_minutes": 90,
  "general_instructions": ["..."],
  "sections": [
    {
      "name": "A",
      "instructions": "Multiple choice questions, 1 mark each.",
      "question_type": "MCQ",       // MCQ | VSA | SA | LA | CASE_STUDY
      "num_questions": 10,
      "num_to_attempt": null,       // set if this section offers internal choice
      "marks_per_question": 1,
      "difficulty_mix": { "easy": 0.5, "medium": 0.4, "hard": 0.1 }
    }
  ]
}
```

Non-technical editing path: the Admin page's pattern editor is a proper
form — name/subject/grade fields, a repeatable "Sections" list (name,
question type dropdown, question count, marks, optional internal-choice
count, optional difficulty mix), with total marks/questions computed and
shown live. No JSON is required day-to-day. Required fields use native
browser validation (a name/count/marks left blank is caught before the
request is even sent), and the payload is still validated server-side
against `config/pattern.schema.json` as a second line of defense. Power
users get an "Advanced: view/edit raw JSON" panel (collapsed by default)
that mirrors the form live and can be pasted into or out of — editing the
JSON and clicking "Apply" loads it back into the form fields, which stay
the single source of truth for what actually gets saved. See
`frontend/js/admin.js` (`formToConfig`/`configToForm`).

## 6. Generation contract

Input: a `Pattern`'s `config_json` + up to ~12,000 characters of combined
extracted text from the selected `SourceDocument`s + free-text extra
instructions.

DeepSeek is instructed (see `SYSTEM_PROMPT` in
`backend/app/services/generation.py`) to act as a CBSE paper-setter and
return exactly one question per blueprint slot, as JSON:

```jsonc
{
  "questions": [
    {
      "section": "A", "question_type": "MCQ", "text": "...",
      "options": ["...", "...", "...", "..."],   // MCQ only, else null
      "marks": 1, "difficulty": "easy",
      "expected_answer": "...", "rubric": "..."
    }
  ]
}
```

**Count enforcement:** after each response, the actual per-section question
counts are compared against the blueprint's `num_questions`. On a mismatch,
generation retries once with an added note telling the model exactly what
was wrong (e.g. `section 'A': expected 10, got 8`). If the retry still
doesn't match, the `QuestionSet` is marked `failed` with that description
in `error_message` rather than silently saving a partial/incorrect set —
nothing partially-generated ever reaches the printable view. See
`_expected_section_counts`/`_actual_section_counts`/`_describe_count_mismatch`
in `generation.py`, and `backend/tests/test_generation.py` for the retry
and failure paths (exercised by stubbing `deepseek_client.chat_json`,
independent of mock mode).

## 7. Evaluation contract

Input: every `Question` in the `QuestionSet` (including hidden
`expected_answer`/`rubric`) + the submitted image(s), sent directly to
DeepSeek's vision-capable model (no local OCR step — see README
"Limitations").

DeepSeek is instructed (see `SYSTEM_PROMPT` in
`backend/app/services/evaluation.py`) to locate each answer in the image(s)
by content (not by position), grade it against the rubric with partial
credit where reasonable, and return:

```jsonc
{
  "overall_feedback": "...",
  "items": [
    {
      "question_order_index": 0,   // matches Question.order_index, not DB id
      "extracted_answer": "...", "marks_awarded": 1, "marks_possible": 1,
      "is_correct": true, "feedback": "..."
    }
  ]
}
```

Items are matched back to `Question` rows by `order_index` (their position
in the set), since the model only sees the paper content, not database IDs.

## 8. Mock mode

Controlled centrally in `config.py` (`effective_mock_mode`): true whenever
`DEEPSEEK_API_KEY` is empty, or `MOCK_MODE=true` is set explicitly. Both
`chat_json` and `vision_json` in `deepseek_client.py` short-circuit to
deterministic placeholder data in this case — same shape a real response
would have, clearly labelled `[MOCK]`. This means:

- The entire UI is click-through-able with zero configuration.
- Automated tests (`backend/tests/`) run without hitting the network.
- Turning on real generation/grading is a one-line `.env` change, not a
  code change.

## 9. API surface (all under `/api`, JSON unless noted)

| Method & path | Purpose |
|---|---|
| `GET /health` | `{status, mock_mode}` |
| `GET/POST /source-documents` | list / upload (multipart) a past paper |
| `DELETE /source-documents/{id}` | remove a document (and its file) |
| `GET/POST /patterns` | list / create a pattern |
| `GET /patterns/schema` | the pattern JSON Schema (for building a form) |
| `GET/PUT/DELETE /patterns/{id}` | fetch / update / delete one pattern |
| `GET /question-sets` | list all generated sets |
| `POST /question-sets/generate` | generate 1-10 sets from a pattern |
| `GET /question-sets/{id}` | student-facing view (no answer key) |
| `GET /question-sets/{id}/answer-key` | teacher-facing view (with answer key) |
| `DELETE /question-sets/{id}` | remove a set |
| `GET/POST /submissions` | list / create (multipart images) a submission |
| `POST /submissions/{id}/evaluate` | run grading, returns the graded submission |
| `GET /submissions/{id}` | fetch one submission + its evaluation |

## 10. Non-goals (by design, for this local/single-family use case)

- No user accounts, login, or multi-tenant isolation.
- No cloud deployment, background job queue, or webhook infrastructure —
  generation and evaluation run synchronously within the HTTP request.
- No payment/quota tracking for DeepSeek usage — that's on DeepSeek's
  dashboard, not this app.

## 11. Natural next steps (not built, but the code is shaped to allow them)

- A local-OCR fallback (Tesseract) ahead of grading, if DeepSeek vision
  accuracy on real handwriting turns out to need it — isolated to
  `evaluation.py`/`deepseek_client.py`. Deliberately not built yet: the
  chosen architecture sends photos straight to DeepSeek's vision model
  (see §7), and this would only be worth adding if that proves unreliable
  in practice.
- Multiple children/profiles if this ever needs to serve more than one kid
  from the same install.
- `GET /api/patterns/schema` already exists (served for tooling/API
  consumers) but the Admin form (§5) doesn't derive itself from it — the
  form's fields were hand-built to match the schema. If the schema changes
  meaningfully, both need updating together today.
