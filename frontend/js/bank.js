const paperFilter = document.getElementById("paper-filter");
const topicFilter = document.getElementById("topic-filter");

function topicChips(topics) {
  if (!topics.length) return '<span class="text-xs text-gray-400">untagged</span>';
  return topics.map((t) => `<span class="chip">${escapeHtml(t)}</span>`).join(" ");
}

function markSchemeHtml(q) {
  if (q.ms_image_url) {
    return `<img class="question-img mt-2" src="${q.ms_image_url}" alt="Mark scheme for ${escapeHtml(q.source_label)}" loading="lazy" />`;
  }
  return '<p class="text-xs text-gray-500 mt-2">No mark scheme entry for this question.</p>';
}

function questionCard(q) {
  const flags = q.flags.length
    ? `<ul class="text-xs mt-2 p-2 rounded border bg-amber-50 border-amber-200 text-amber-800">${q.flags
        .map((f) => `<li>⚠️ ${escapeHtml(f)}</li>`)
        .join("")}</ul>`
    : "";
  return `
    <div class="card p-4">
      <div class="flex justify-between items-start gap-4 mb-2">
        <div>
          <span class="font-semibold">${escapeHtml(q.source_label)}</span>
          <span class="text-sm text-gray-500"> · ${q.marks} mark${q.marks == 1 ? "" : "s"}</span>
        </div>
        <div class="text-right">${topicChips(q.topics)}</div>
      </div>
      ${flags}
      <img class="question-img mt-2" src="${q.image_url}" alt="${escapeHtml(q.source_label)}" loading="lazy" />
      <details class="mt-2">
        <summary class="text-sm text-gray-600 cursor-pointer">Mark scheme</summary>
        ${markSchemeHtml(q)}
      </details>
      <details class="mt-1">
        <summary class="text-sm text-gray-600 cursor-pointer">Extracted text (used for topic tagging and grading)</summary>
        <pre class="extracted-text">${escapeHtml(q.text)}</pre>
      </details>
    </div>`;
}

async function loadFilters() {
  const params = new URLSearchParams(location.search);
  const [papers, topics] = await Promise.all([Api.get("/api/past-papers"), Api.get("/api/bank-questions/topics")]);
  paperFilter.innerHTML =
    '<option value="">All papers</option>' +
    papers
      .filter((p) => p.status === "ready")
      .map((p) => `<option value="${p.id}">${escapeHtml(p.title)}</option>`)
      .join("");
  topicFilter.innerHTML =
    '<option value="">Any topic</option>' +
    topics.map((t) => `<option value="${escapeHtml(t.topic)}">${escapeHtml(t.topic)} (${t.count})</option>`).join("");
  paperFilter.value = params.get("paper") || "";
}

async function loadQuestions() {
  const list = document.getElementById("question-list");
  const summary = document.getElementById("summary");
  list.innerHTML = "Loading…";
  const query = new URLSearchParams();
  if (paperFilter.value) query.set("past_paper_id", paperFilter.value);
  if (topicFilter.value) query.set("topic", topicFilter.value);
  try {
    const questions = await Api.get(`/api/bank-questions?${query}`);
    const marks = questions.reduce((sum, q) => sum + q.marks, 0);
    const flagged = questions.filter((q) => q.flags.length).length;
    summary.textContent = `${questions.length} question(s) · ${marks} marks${flagged ? ` · ${flagged} flagged` : ""}`;
    list.innerHTML = questions.length
      ? questions.map(questionCard).join("")
      : '<p class="text-sm text-gray-500">No questions yet — upload a past paper in Admin.</p>';
  } catch (e) {
    list.innerHTML = `<p class="text-sm text-red-600">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
}

paperFilter.addEventListener("change", loadQuestions);
topicFilter.addEventListener("change", loadQuestions);
loadFilters()
  .catch((e) => toast(e.message, "error"))
  .finally(loadQuestions);
