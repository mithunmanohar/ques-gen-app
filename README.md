# Question Set Studio

A local web app that turns CBSE past-year question papers into fresh,
pattern-matched practice question sets using DeepSeek, and grades your
child's photographed answer sheets against them.

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

1. **Admin** (`/admin.html`) — upload past-year papers (PDF, Markdown, or
   plain text) as reference material, and define/edit **patterns**: the
   exam blueprint (sections, question types, marks, question counts) that
   generation follows. A sample CBSE Class 10 Science pattern is included
   in `config/patterns/`.
2. **Generate** (`/generate.html`) — pick a pattern and, optionally,
   reference documents, and generate one or more new question sets.
   DeepSeek writes fresh questions matching the blueprint, plus a hidden
   answer key used later for grading. View or print any set from here.
3. **Submit & Evaluate** (`/evaluate.html`) — print a set, have your child
   solve it on paper, photograph the completed sheet, and upload it here.
   DeepSeek reads the handwriting directly from the photo(s) and grades it
   against the hidden answer key, question by question, with feedback.

## Architecture, briefly

- **Backend:** FastAPI + SQLAlchemy + SQLite (`backend/app/`). No auth —
  this is a single-user local app.
- **Frontend:** plain HTML/CSS/JS, no framework, no build step
  (`frontend/`), served as static files directly by FastAPI.
- **Storage:** everything lives under `data/` (gitignored): the SQLite
  database, uploaded source documents, and submitted answer-sheet photos.
  Delete that folder any time to reset the app to a blank slate.
- **Spec-driven generation:** the exam blueprint is a JSON document
  validated against [`config/pattern.schema.json`](config/pattern.schema.json).
  Edit it by hand, or through the form in the Admin page.

## Limitations / things to know

- **PDF text extraction** only works on text-based PDFs. A scanned/photographed
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
frontend/                No-build-step static HTML/CSS/JS
config/
  pattern.schema.json    The pattern "spec"
  patterns/                Example pattern JSON files
data/                     Runtime data (gitignored): db, uploads
```
