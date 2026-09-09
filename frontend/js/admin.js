const SAMPLE_PATTERN = {
  name: "CBSE Class 10 Science - Sample Paper Pattern",
  subject: "Science",
  grade: "10",
  total_marks: 49,
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

// ---------- Patterns ----------

function fillPatternForm(pattern) {
  const form = document.getElementById("pattern-form");
  form.id.value = pattern?.id ?? "";
  form.name.value = pattern?.name ?? SAMPLE_PATTERN.name;
  form.subject.value = pattern?.subject ?? SAMPLE_PATTERN.subject;
  form.grade.value = pattern?.grade ?? SAMPLE_PATTERN.grade;
  form.config_json.value = JSON.stringify(pattern?.config_json ?? SAMPLE_PATTERN, null, 2);
}

document.getElementById("pattern-reset").addEventListener("click", () => fillPatternForm(null));

async function loadPatterns() {
  const list = document.getElementById("pattern-list");
  list.innerHTML = "Loading…";
  try {
    const patterns = await Api.get("/api/patterns");
    if (!patterns.length) {
      list.innerHTML = '<p class="text-sm text-gray-500">No patterns saved yet — the form above is pre-filled with a sample.</p>';
      return;
    }
    list.innerHTML = patterns
      .map((p) => {
        const totalQ = p.config_json.sections.reduce((s, sec) => s + sec.num_questions, 0);
        return `
      <div class="card p-4 flex justify-between items-start gap-4">
        <div>
          <div class="font-semibold">${escapeHtml(p.name)}</div>
          <div class="text-xs text-gray-500">${escapeHtml(p.subject)} ${p.grade ? "· Grade " + escapeHtml(p.grade) : ""} · ${p.config_json.sections.length} sections · ${totalQ} questions</div>
        </div>
        <div class="flex gap-2">
          <button class="btn btn-secondary" onclick='fillPatternForm(${JSON.stringify(p).replace(/'/g, "&apos;")})'>Edit</button>
          <button class="btn btn-danger" onclick="deletePattern(${p.id})">Delete</button>
        </div>
      </div>`;
      })
      .join("");
  } catch (e) {
    list.innerHTML = `<p class="text-sm text-red-600">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
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

document.getElementById("pattern-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  let configJson;
  try {
    configJson = JSON.parse(form.config_json.value);
  } catch (e) {
    toast(`Invalid JSON: ${e.message}`, "error");
    return;
  }
  const payload = {
    name: form.name.value,
    subject: form.subject.value,
    grade: form.grade.value,
    config_json: configJson,
  };
  try {
    if (form.id.value) {
      await Api.putJson(`/api/patterns/${form.id.value}`, payload);
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
