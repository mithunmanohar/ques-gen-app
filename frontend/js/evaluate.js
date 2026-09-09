const params = new URLSearchParams(location.search);
const preselectSetId = params.get("set");

async function loadSetOptions() {
  const select = document.getElementById("set-select");
  try {
    const sets = await Api.get("/api/question-sets");
    const ready = sets.filter((s) => s.status === "ready");
    if (!ready.length) {
      select.innerHTML = '<option value="">No ready question sets — generate one first</option>';
      return;
    }
    select.innerHTML = ready
      .map((s) => `<option value="${s.id}" ${String(s.id) === preselectSetId ? "selected" : ""}>${escapeHtml(s.name)}</option>`)
      .join("");
  } catch (e) {
    select.innerHTML = "<option>Failed to load question sets</option>";
  }
}

function statusBadge(status) {
  return `<span class="badge badge-${status}">${status}</span>`;
}

function renderEvaluation(submission) {
  const ev = submission.evaluation;
  if (!ev) {
    return `<p class="text-sm text-gray-500">Not evaluated yet.</p>`;
  }
  const pct = ev.total_marks_possible ? Math.round((ev.total_marks_awarded / ev.total_marks_possible) * 100) : 0;
  let html = `
    <div class="mb-3">
      <span class="text-2xl font-bold">${ev.total_marks_awarded} / ${ev.total_marks_possible}</span>
      <span class="text-gray-500"> (${pct}%)</span>
      ${ev.is_mocked ? '<span class="badge badge-generating ml-2">mock</span>' : ""}
    </div>
    <p class="text-sm text-gray-700 mb-4">${escapeHtml(ev.overall_feedback)}</p>
    <table class="w-full text-sm border-collapse">
      <thead><tr class="text-left border-b">
        <th class="py-1 pr-2">#</th><th class="py-1 pr-2">Extracted answer</th>
        <th class="py-1 pr-2">Marks</th><th class="py-1">Feedback</th>
      </tr></thead>
      <tbody>`;
  ev.items.forEach((item, i) => {
    html += `<tr class="border-b align-top">
      <td class="py-1 pr-2">${i + 1}</td>
      <td class="py-1 pr-2">${escapeHtml(item.extracted_answer)}</td>
      <td class="py-1 pr-2 whitespace-nowrap">${item.is_correct ? "✅" : "❌"} ${item.marks_awarded}/${item.marks_possible}</td>
      <td class="py-1">${escapeHtml(item.feedback)}</td>
    </tr>`;
  });
  html += `</tbody></table>`;
  return html;
}

async function loadSubmissions() {
  const list = document.getElementById("submission-list");
  list.innerHTML = "Loading…";
  try {
    const submissions = await Api.get("/api/submissions");
    if (!submissions.length) {
      list.innerHTML = '<p class="text-sm text-gray-500">No submissions yet.</p>';
      return;
    }
    list.innerHTML = submissions
      .map(
        (s) => `
      <div class="card p-4">
        <div class="flex justify-between items-start gap-4">
          <div>
            <div class="font-semibold">${escapeHtml(s.student_name || "(unnamed)")} ${statusBadge(s.status)}</div>
            <div class="text-xs text-gray-500">Set #${s.question_set_id} · ${new Date(s.submitted_at).toLocaleString()} · ${s.images.length} image(s)</div>
            ${s.status === "failed" ? `<div class="text-xs text-red-600 mt-1">${escapeHtml(s.error_message)}</div>` : ""}
          </div>
        </div>
        ${s.evaluation ? `<div class="mt-3 pt-3 border-t">${renderEvaluation(s)}</div>` : ""}
      </div>`
      )
      .join("");
  } catch (e) {
    list.innerHTML = `<p class="text-sm text-red-600">Failed to load: ${escapeHtml(e.message)}</p>`;
  }
}

document.getElementById("submit-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const form = ev.target;
  const btn = document.getElementById("submit-btn");
  if (!form.question_set_id.value) {
    toast("Choose a question set first", "error");
    return;
  }
  btn.disabled = true;
  const resultSection = document.getElementById("result-section");
  const resultEl = document.getElementById("result");
  resultSection.classList.remove("hidden");
  try {
    btn.textContent = "Uploading…";
    const formData = new FormData(form);
    const submission = await Api.postForm("/api/submissions", formData);

    btn.textContent = "Grading with DeepSeek… this can take up to a minute";
    resultEl.innerHTML = '<p class="text-sm text-gray-500">Grading in progress…</p>';
    const graded = await Api.postJson(`/api/submissions/${submission.id}/evaluate`, {});

    resultEl.innerHTML = renderEvaluation(graded);
    toast("Graded!");
    form.reset();
    loadSubmissions();
  } catch (e) {
    resultEl.innerHTML = `<p class="text-red-600">${escapeHtml(e.message)}</p>`;
    toast(e.message, "error");
  } finally {
    btn.disabled = false;
    btn.textContent = "Upload & grade";
  }
});

loadSetOptions();
loadSubmissions();
