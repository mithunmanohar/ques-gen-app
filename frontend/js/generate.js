async function loadPatternOptions() {
  const select = document.getElementById("pattern-select");
  try {
    const patterns = await Api.get("/api/patterns");
    if (!patterns.length) {
      select.innerHTML = '<option value="">No patterns yet — create one in Admin first</option>';
      return;
    }
    select.innerHTML = patterns
      .map((p) => `<option value="${p.id}">${escapeHtml(p.name)}${p.grade ? " (Grade " + escapeHtml(p.grade) + ")" : ""}</option>`)
      .join("");
  } catch (e) {
    select.innerHTML = "<option>Failed to load patterns</option>";
  }
}

async function loadSourceDocChecks() {
  const container = document.getElementById("source-doc-checks");
  try {
    const docs = await Api.get("/api/source-documents");
    if (!docs.length) {
      container.innerHTML = "No source documents uploaded yet (optional — generation still works without them).";
      return;
    }
    container.innerHTML = docs
      .map(
        (d) => `<label class="flex items-center gap-2 py-0.5">
          <input type="checkbox" name="source_doc" value="${d.id}" />
          ${escapeHtml(d.title)} <span class="text-xs text-gray-400">(${escapeHtml(d.subject)})</span>
        </label>`
      )
      .join("");
  } catch (e) {
    container.innerHTML = "Failed to load source documents.";
  }
}

async function loadBankChecks() {
  const papersEl = document.getElementById("bank-paper-checks");
  const topicsEl = document.getElementById("bank-topic-checks");
  try {
    const [papers, topics] = await Promise.all([Api.get("/api/past-papers"), Api.get("/api/bank-questions/topics")]);
    const ready = papers.filter((p) => p.status === "ready");
    papersEl.innerHTML = ready.length
      ? ready
          .map(
            (p) => `<label class="flex items-center gap-2 py-0.5">
          <input type="checkbox" name="bank_paper" value="${p.id}" />
          ${escapeHtml(p.title)} <span class="text-xs text-gray-400">(${p.question_count} Qs, ${p.total_marks} marks${p.flagged_count ? `, ${p.flagged_count} flagged` : ""})</span>
        </label>`
          )
          .join("")
      : 'No past papers in the bank yet — upload some in <a href="/admin.html">Admin</a>.';
    topicsEl.innerHTML = topics.length
      ? topics
          .map(
            (t) => `<label class="flex items-center gap-2 py-0.5">
          <input type="checkbox" name="bank_topic" value="${escapeHtml(t.topic)}" />
          ${escapeHtml(t.topic)} <span class="text-xs text-gray-400">(${t.count})</span>
        </label>`
          )
          .join("")
      : "No topics tagged yet (topics are tagged by DeepSeek on upload; mock mode leaves them blank).";
  } catch (e) {
    papersEl.innerHTML = "Failed to load past papers.";
  }
}

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

async function loadQuestionSets() {
  const list = document.getElementById("set-list");
  list.innerHTML = "Loading…";
  try {
    const sets = await Api.get("/api/question-sets");
    if (!sets.length) {
      list.innerHTML = '<p class="text-sm text-gray-500">No question sets generated yet.</p>';
      return;
    }
    list.innerHTML = sets
      .map(
        (s) => `
      <div class="card p-4 flex justify-between items-start gap-4">
        <div>
          <div class="font-semibold">${escapeHtml(s.name)} ${statusBadge(s.status)}
            <span class="badge badge-source">${s.source === "bank" ? "past-paper bank" : "AI-generated"}</span></div>
          <div class="text-xs text-gray-500">${escapeHtml(s.subject)} ${s.grade ? "· Grade " + escapeHtml(s.grade) : ""} · ${s.questions.length} questions · ${s.questions.reduce((sum, q) => sum + q.marks, 0)} marks · ${new Date(s.generated_at).toLocaleString()}</div>
          ${s.error_message ? `<div class="text-xs ${s.status === "failed" ? "text-red-600" : "text-amber-700"} mt-1">${escapeHtml(s.error_message)}</div>` : ""}
        </div>
        <div class="flex gap-2 flex-wrap justify-end">
          <a class="btn btn-secondary" href="/set.html?id=${s.id}" target="_blank">View / Print</a>
          <a class="btn btn-secondary" href="/set.html?id=${s.id}&key=1" target="_blank">Answer key</a>
          <a class="btn btn-primary" href="/evaluate.html?set=${s.id}">Submit answer</a>
          <button class="btn btn-danger" onclick="deleteSet(${s.id})">Delete</button>
        </div>
      </div>`
      )
      .join("");
  } catch (e) {
    list.innerHTML = `<p class="text-sm text-red-600">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
}

async function deleteSet(id) {
  if (!confirm("Delete this question set and any submissions against it?")) return;
  try {
    await Api.del(`/api/question-sets/${id}`);
    toast("Question set deleted");
    loadQuestionSets();
  } catch (e) {
    toast(e.message, "error");
  }
}

document.getElementById("generate-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const btn = document.getElementById("generate-btn");
  const sourceIds = Array.from(form.querySelectorAll('input[name="source_doc"]:checked')).map((el) => Number(el.value));
  const payload = {
    pattern_id: Number(form.pattern_id.value),
    name: form.name.value,
    num_sets: Number(form.num_sets.value) || 1,
    source_document_ids: sourceIds,
    extra_instructions: form.extra_instructions.value,
  };
  if (!payload.pattern_id) {
    toast("Choose a pattern first", "error");
    return;
  }
  btn.disabled = true;
  btn.textContent = "Generating… (this calls DeepSeek and can take a little while)";
  try {
    const results = await Api.postJson("/api/question-sets/generate", payload);
    const failed = results.filter((r) => r.status === "failed");
    toast(failed.length ? `${results.length - failed.length} set(s) generated, ${failed.length} failed` : `${results.length} set(s) generated`, failed.length ? "error" : "success");
    loadQuestionSets();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Generate";
  }
});

document.getElementById("bank-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const btn = document.getElementById("bank-btn");
  const payload = {
    name: form.name.value,
    target_marks: Number(form.target_marks.value),
    num_sets: Number(form.num_sets.value) || 1,
    past_paper_ids: Array.from(form.querySelectorAll('input[name="bank_paper"]:checked')).map((el) => Number(el.value)),
    topics: Array.from(form.querySelectorAll('input[name="bank_topic"]:checked')).map((el) => el.value),
    avoid_used: form.avoid_used.checked,
    include_flagged: form.include_flagged.checked,
  };
  btn.disabled = true;
  try {
    const results = await Api.postJson("/api/question-sets/from-bank", payload);
    const short = results.filter((r) => r.error_message);
    toast(
      short.length ? `${results.length} set(s) built — ${short[0].error_message}` : `${results.length} set(s) built`,
      short.length ? "error" : "success"
    );
    loadQuestionSets();
  } catch (e) {
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
  }
});

loadBankChecks();
loadPatternOptions();
loadSourceDocChecks();
loadQuestionSets();
