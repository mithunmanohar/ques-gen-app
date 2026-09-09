const SAMPLE_PATTERN = {
  name: "CBSE Class 10 Science - Sample Paper Pattern",
  subject: "Science",
  grade: "10",
  duration_minutes: 90,
  general_instructions: [
    "All questions are compulsory unless internal choice is indicated.",
    "Section A has multiple choice questions.",
  ],
  sections: [
    {
      name: "A",
      instructions: "Multiple choice questions, 1 mark each.",
      question_type: "MCQ",
      num_questions: 10,
      marks_per_question: 1,
      difficulty_mix: { easy: 0.5, medium: 0.4, hard: 0.1 },
    },
    {
      name: "B",
      instructions: "Very short answer questions, 2 marks each.",
      question_type: "VSA",
      num_questions: 5,
      marks_per_question: 2,
    },
    {
      name: "C",
      instructions: "Short answer questions, 3 marks each. Attempt any 4 of 5.",
      question_type: "SA",
      num_questions: 5,
      num_to_attempt: 4,
      marks_per_question: 3,
    },
    {
      name: "D",
      instructions: "Long answer questions, 5 marks each.",
      question_type: "LA",
      num_questions: 2,
      marks_per_question: 5,
    },
  ],
};

const QUESTION_TYPES = [
  ["MCQ", "MCQ — multiple choice"],
  ["VSA", "VSA — very short answer"],
  ["SA", "SA — short answer"],
  ["LA", "LA — long answer"],
  ["CASE_STUDY", "Case study / passage-based"],
];

// ---------- Source documents ----------

async function loadDocs() {
  const list = document.getElementById("doc-list");
  list.innerHTML = "Loading…";
  try {
    const docs = await Api.get("/api/source-documents");
    if (!docs.length) {
      list.innerHTML = '<p class="text-sm text-gray-500">No documents uploaded yet.</p>';
      return;
    }
    list.innerHTML = docs
      .map(
        (d) => `
      <div class="card p-4 flex justify-between items-start gap-4">
        <div>
          <div class="font-semibold">${escapeHtml(d.title)}
            <span class="text-xs text-gray-500 font-normal">(${escapeHtml(d.file_type)})</span>
          </div>
          <div class="text-xs text-gray-500 mb-1">${escapeHtml(d.subject)} ${d.grade ? "· Grade " + escapeHtml(d.grade) : ""} ${d.chapter ? "· " + escapeHtml(d.chapter) : ""}</div>
          <div class="text-xs text-gray-400">${escapeHtml(d.text_preview).slice(0, 200)}${d.text_preview.length > 200 ? "…" : ""}</div>
          ${!d.text_preview ? '<div class="text-xs text-amber-600 mt-1">⚠️ No text could be extracted — likely a scanned/image-only PDF.</div>' : ""}
        </div>
        <button class="btn btn-danger" onclick="deleteDoc(${d.id})">Delete</button>
      </div>`
      )
      .join("");
  } catch (e) {
    list.innerHTML = `<p class="text-sm text-red-600">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
}

async function deleteDoc(id) {
  if (!confirm("Delete this document?")) return;
  try {
    await Api.del(`/api/source-documents/${id}`);
    toast("Document deleted");
    loadDocs();
  } catch (e) {
    toast(e.message, "error");
  }
}

document.getElementById("doc-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const formData = new FormData(form);
  try {
    await Api.postForm("/api/source-documents", formData);
    toast("Document uploaded");
    form.reset();
    loadDocs();
  } catch (e) {
    toast(e.message, "error");
  }
});

// ---------- Pattern builder (form-driven; no JSON editing required) ----------

let sectionUid = 0;
const sectionsContainer = document.getElementById("sections-container");
const patternForm = document.getElementById("pattern-form");
const jsonView = document.getElementById("pattern-json-view");

function sectionRowHtml(section = {}) {
  const uid = `s${sectionUid++}`;
  const diff = section.difficulty_mix || {};
  const typeOptions = QUESTION_TYPES.map(
    ([value, label]) =>
      `<option value="${value}" ${section.question_type === value ? "selected" : ""}>${escapeHtml(label)}</option>`
  ).join("");
  return `
    <div class="section-row card p-3 space-y-2" data-uid="${uid}">
      <div class="grid sm:grid-cols-2 gap-3">
        <div class="field"><label>Section name</label>
          <input type="text" class="sec-name" placeholder="A" required value="${escapeHtml(section.name ?? "")}" /></div>
        <div class="field"><label>Question type</label>
          <select class="sec-qtype">${typeOptions}</select></div>
        <div class="field"><label>Number of questions</label>
          <input type="number" min="1" required class="sec-num" value="${section.num_questions ?? ""}" /></div>
        <div class="field"><label>Marks per question</label>
          <input type="number" min="0" step="0.5" required class="sec-marks" value="${section.marks_per_question ?? ""}" /></div>
        <div class="field sm:col-span-2"><label>Instructions (printed on the paper, optional)</label>
          <input type="text" class="sec-instructions" value="${escapeHtml(section.instructions ?? "")}" /></div>
        <div class="field"><label>Attempt how many? (blank = all compulsory)</label>
          <input type="number" min="1" class="sec-attempt" value="${section.num_to_attempt ?? ""}" /></div>
      </div>
      <details>
        <summary class="text-xs cursor-pointer">Difficulty mix (optional, should add up to ~1)</summary>
        <div class="grid sm:grid-cols-3 gap-3 mt-2">
          <div class="field"><label>Easy</label><input type="number" min="0" max="1" step="0.1" class="sec-diff-easy" value="${diff.easy ?? ""}" /></div>
          <div class="field"><label>Medium</label><input type="number" min="0" max="1" step="0.1" class="sec-diff-medium" value="${diff.medium ?? ""}" /></div>
          <div class="field"><label>Hard</label><input type="number" min="0" max="1" step="0.1" class="sec-diff-hard" value="${diff.hard ?? ""}" /></div>
        </div>
      </details>
      <button type="button" class="btn btn-danger remove-section-btn">Remove section</button>
    </div>`;
}

function addSectionRow(section = {}) {
  sectionsContainer.insertAdjacentHTML("beforeend", sectionRowHtml(section));
}

function renderSections(sections) {
  sectionsContainer.innerHTML = "";
  (sections && sections.length ? sections : [{}]).forEach(addSectionRow);
  onFormChanged();
}

function readSectionsFromForm() {
  return Array.from(sectionsContainer.querySelectorAll(".section-row")).map((row) => {
    const val = (sel) => row.querySelector(sel).value;
    const section = {
      name: val(".sec-name"),
      question_type: val(".sec-qtype"),
      num_questions: Number(val(".sec-num")) || 0,
      marks_per_question: Number(val(".sec-marks")) || 0,
      instructions: val(".sec-instructions"),
    };
    const attempt = val(".sec-attempt");
    if (attempt) section.num_to_attempt = Number(attempt);
    const easy = val(".sec-diff-easy"),
      medium = val(".sec-diff-medium"),
      hard = val(".sec-diff-hard");
    if (easy || medium || hard) {
      section.difficulty_mix = {};
      if (easy) section.difficulty_mix.easy = Number(easy);
      if (medium) section.difficulty_mix.medium = Number(medium);
      if (hard) section.difficulty_mix.hard = Number(hard);
    }
    return section;
  });
}

function formToConfig() {
  const sections = readSectionsFromForm();
  const totalMarks = sections.reduce((sum, s) => sum + s.num_questions * s.marks_per_question, 0);
  const config = {
    name: patternForm.name.value,
    subject: patternForm.subject.value,
    grade: patternForm.grade.value,
    total_marks: totalMarks,
    sections,
  };
  const duration = patternForm.duration_minutes.value;
  if (duration) config.duration_minutes = Number(duration);
  const instructions = patternForm.general_instructions.value
    .split("\n")
    .map((s) => s.trim())
    .filter(Boolean);
  if (instructions.length) config.general_instructions = instructions;
  return config;
}

function configToForm(config) {
  patternForm.name.value = config.name ?? "";
  patternForm.subject.value = config.subject ?? "";
  patternForm.grade.value = config.grade ?? "";
  patternForm.duration_minutes.value = config.duration_minutes ?? "";
  patternForm.general_instructions.value = (config.general_instructions ?? []).join("\n");
  renderSections(config.sections ?? []);
}

function onFormChanged() {
  const config = formToConfig();
  const totalQuestions = config.sections.reduce((sum, s) => sum + (s.num_questions || 0), 0);
  document.getElementById("pattern-totals").textContent =
    `Total: ${config.sections.length} section(s), ${totalQuestions} question(s), ${config.total_marks} mark(s).`;
  jsonView.value = JSON.stringify(config, null, 2);
}

patternForm.addEventListener("input", onFormChanged);

document.getElementById("add-section-btn").addEventListener("click", () => {
  addSectionRow({});
  onFormChanged();
});

sectionsContainer.addEventListener("click", (ev) => {
  if (ev.target.classList.contains("remove-section-btn")) {
    const rows = sectionsContainer.querySelectorAll(".section-row");
    if (rows.length <= 1) {
      toast("A pattern needs at least one section", "error");
      return;
    }
    ev.target.closest(".section-row").remove();
    onFormChanged();
  }
});

document.getElementById("json-apply-btn").addEventListener("click", () => {
  try {
    const config = JSON.parse(jsonView.value);
    configToForm(config);
    toast("JSON applied to the form above");
  } catch (e) {
    toast(`Invalid JSON: ${e.message}`, "error");
  }
});

function fillPatternForm(pattern) {
  patternForm.id.value = pattern?.id ?? "";
  configToForm(pattern?.config_json ?? SAMPLE_PATTERN);
}

document.getElementById("pattern-reset").addEventListener("click", () => fillPatternForm(null));

let patternsCache = [];

async function loadPatterns() {
  const list = document.getElementById("pattern-list");
  list.innerHTML = "Loading…";
  try {
    patternsCache = await Api.get("/api/patterns");
    if (!patternsCache.length) {
      list.innerHTML = '<p class="text-sm text-gray-500">No patterns saved yet — the form above is pre-filled with a sample.</p>';
      return;
    }
    list.innerHTML = patternsCache
      .map((p) => {
        const totalQ = p.config_json.sections.reduce((s, sec) => s + sec.num_questions, 0);
        return `
      <div class="card p-4 flex justify-between items-start gap-4">
        <div>
          <div class="font-semibold">${escapeHtml(p.name)}</div>
          <div class="text-xs text-gray-500">${escapeHtml(p.subject)} ${p.grade ? "· Grade " + escapeHtml(p.grade) : ""} · ${p.config_json.sections.length} sections · ${totalQ} questions</div>
        </div>
        <div class="flex gap-2">
          <button class="btn btn-secondary" onclick="editPattern(${p.id})">Edit</button>
          <button class="btn btn-danger" onclick="deletePattern(${p.id})">Delete</button>
        </div>
      </div>`;
      })
      .join("");
  } catch (e) {
    list.innerHTML = `<p class="text-sm text-red-600">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
}

function editPattern(id) {
  const pattern = patternsCache.find((p) => p.id === id);
  if (!pattern) return;
  fillPatternForm(pattern);
  window.scrollTo({ top: patternForm.offsetTop - 20, behavior: "smooth" });
}

async function deletePattern(id) {
  if (!confirm("Delete this pattern? Existing generated question sets that used it are kept.")) return;
  try {
    await Api.del(`/api/patterns/${id}`);
    toast("Pattern deleted");
    loadPatterns();
  } catch (e) {
    toast(e.message, "error");
  }
}

patternForm.addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const configJson = formToConfig();
  const payload = {
    name: configJson.name,
    subject: configJson.subject,
    grade: configJson.grade,
    config_json: configJson,
  };
  try {
    if (patternForm.id.value) {
      await Api.putJson(`/api/patterns/${patternForm.id.value}`, payload);
    } else {
      await Api.postJson("/api/patterns", payload);
    }
    toast("Pattern saved");
    fillPatternForm(null);
    loadPatterns();
  } catch (e) {
    toast(e.message, "error");
  }
});

fillPatternForm(null);
loadDocs();
loadPatterns();
