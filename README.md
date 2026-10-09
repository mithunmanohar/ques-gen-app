# Question Set Studio

A local web app that builds practice question sets for your child and
grades their photographed answer sheets. Sets come from either of two
sources:

- **The past-paper bank:** upload Cambridge (CAIE) question papers and mark
  schemes. Every question is cropped out automatically as an image,
  diagrams included, with its official answer attached. New papers are
  then assembled from these real questions to a marks target, optionally
  by topic.
- **AI generation:** DeepSeek writes fresh questions that follow an exam
  blueprint ("pattern"), using uploaded past papers as reference material.

Runs entirely on your own laptop. Nothing is deployed to the cloud — the
only outbound network call the app itself makes is to the DeepSeek API
when you generate a question set or grade a submission.

See [`SPEC.md`](SPEC.md) for the full functional/data spec — what each
part of the app does and why it's built this way.

## Quick start

**Requirements:** Python 3.10+.

1. Clone this repo and open a terminal in it.
2. Run the start script for your OS:
   - macOS/Linux: `./run.sh`
   - Windows: `run.bat`

   This creates a virtual environment, installs dependencies, copies
   `.env.example` to `.env` if you don't have one yet, and starts the app.
3. Open **http://localhost:8000** in your browser.

That's it — one process serves both the backend API and the frontend
pages. No Node.js, no separate frontend build step, no Docker.

The app works immediately in **mock mode**: every screen is fully
click-through-able with clearly-labelled placeholder data, so you can try
the whole flow before signing up for anything.

### Adding your DeepSeek API key

Open the `.env` file (created from `.env.example` on first run) and set:

```
DEEPSEEK_API_KEY=sk-...
```

Restart the app (`Ctrl+C`, then re-run the start script). Mock mode turns
off automatically once a key is present.

Get a key at [platform.deepseek.com](https://platform.deepseek.com). Using
the API costs money per request (DeepSeek's pricing, not this app's) — check
their current pricing before generating large numbers of sets.

## How it's used

1. **Admin** (`/admin.html`):
   - **Cambridge past papers:** upload a question paper PDF plus its mark
     scheme PDF. Extraction is fully automatic, with no review step. The
     paper card shows the question count and marks, and lists any warnings
     raised by the automatic checks (see SPEC §12). You download the PDFs
     yourself; the app never fetches them from any website.
   - **Reference documents and patterns** for AI generation: past papers
     or notes (PDF, Markdown or text), and the exam blueprint (sections,
     question types, marks, counts). A sample CBSE Class 10 Science pattern
     is included in `config/patterns/`.
2. **Question bank** (`/bank.html`) — browse every extracted question
   exactly as it will print, with its marks, topics, any warnings, and the
   official mark-scheme rows.
3. **Generate** (`/generate.html`):
   - **From the bank:** set a marks target and optionally pick papers or
     topics. Questions are drawn at random with no repeats and are
     renumbered.
   - **With AI:** pick a pattern and DeepSeek writes new questions plus a
     hidden answer key.

   View or print any set, or its answer key, from here.
4. **Submit & Evaluate** (`/evaluate.html`) — print a set, have your child
   solve it on paper, photograph the completed sheet, and upload it here.
   DeepSeek reads the handwriting directly from the photo(s) and grades it
   against the answer key, question by question, with feedback. For bank
   questions, that key is the official mark scheme.

## Architecture, briefly

- **Backend:** FastAPI + SQLAlchemy + SQLite (`backend/app/`). No auth —
  this is a single-user local app.
- **Frontend:** plain HTML/CSS/JS, no framework, no build step
  (`frontend/`), served as static files directly by FastAPI.
- **Storage:** everything lives under `data/` (gitignored): the SQLite
  database, uploaded source documents, past papers with their cropped
  question images, and submitted answer-sheet photos. Delete that folder
  any time to reset the app to a blank slate. An existing database from an
  older version is upgraded in place on startup.
- **Spec-driven generation:** the exam blueprint is a JSON document
  validated against [`config/pattern.schema.json`](config/pattern.schema.json).
  Edit it by hand, or through the form in the Admin page.

## Limitations / things to know

- **Past-paper extraction** expects born-digital Cambridge PDFs with
  bold question numbers in the left margin, which every recent CAIE paper
  uses. It has been checked against IGCSE Mathematics 0444/21 (Jun 2023),
  0580/41 (Jun 2023) and 0580/22 (Nov 2022): every question and
  mark-scheme row was found, and the marks matched the mark schemes
  exactly. Other layouts may need tuning, as follows:
  - **Multiple-choice papers** (e.g. Paper 1 in some subjects) haven't been
    tried.
  - **Scanned PDFs** are rejected with a clear message.
- **PyMuPDF licence:** the extractor uses PyMuPDF, which is AGPL-3.0. That
  is fine for running this app privately, but redistributing a modified
  version would bring in the AGPL's obligations.
- **Past-paper content** is © UCLES/Cambridge. The bank is meant for your
  own family's practice and is never shared or published anywhere.
- **PDF text extraction** (for reference documents) only works on text-based PDFs. A scanned/photographed
  past paper (image-only PDF) will extract little or no text; the Admin
  page will warn you when that happens. It can still be uploaded, it just
  won't contribute reference text to generation.
- **Grading uses DeepSeek's vision model directly** on the photographed
  answer sheet — there's no separate local OCR step. If handwriting-reading
  accuracy turns out to be a problem in practice, the natural next step is
  adding a local-OCR-then-text-grade pipeline (Tesseract + a text-grading
  prompt); the code is structured so that's a change inside
  `backend/app/services/evaluation.py` and `deepseek_client.py` only.
- **`DEEPSEEK_VISION_MODEL`** in `.env`/`config.py` may need updating —
  DeepSeek's vision-capable model offering and naming has changed over
  time. If grading requests fail with a "model not found"/unsupported
  error, check DeepSeek's current API docs and update that one setting.
- This app has no authentication or multi-user support by design — it's
  meant to run on one person's laptop for their own family's use.

## Running the tests

```
source .venv/bin/activate   # after running run.sh at least once
pytest
```

Tests run entirely in mock mode — no DeepSeek API key or network access
needed.

## Project layout

```
backend/app/
  main.py            FastAPI app, mounts API routers + static frontend
  config.py           All settings (env-var driven)
  models.py            SQLAlchemy tables
  schemas.py            Pydantic request/response models
  routers/               HTTP endpoints (one file per resource)
  services/
    ingestion.py          PDF/Markdown/text -> extracted text
    pattern_validator.py  Validates a pattern against the JSON Schema
    deepseek_client.py    DeepSeek API wrapper (+ mock mode)
    generation.py         Builds the generation prompt, saves the result
    evaluation.py         Builds the grading prompt, saves the result
    paper_extraction.py   Cambridge question paper PDF -> one image per question
    mark_scheme.py        Cambridge mark scheme PDF -> answer rows (+ row images)
    past_paper_import.py  Runs extraction + automatic checks + topic tagging
    topic_tagging.py      DeepSeek topic tags per question (best-effort)
    bank_sets.py          Picks bank questions to a marks target
frontend/                No-build-step static HTML/CSS/JS
config/
  pattern.schema.json    The pattern "spec"
  patterns/                Example pattern JSON files
data/                     Runtime data (gitignored): db, uploads
```
