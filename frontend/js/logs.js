const filters = document.getElementById("log-filters");
const rowsEl = document.getElementById("log-rows");
const summaryEl = document.getElementById("log-summary");
const autoRefresh = document.getElementById("auto-refresh");

const params = new URLSearchParams(location.search);
if (params.get("request_id")) {
  filters.request_id.value = params.get("request_id");
  filters.level.value = "DEBUG";
}

function kv(label, value) {
  return `<div><div class="stat-label">${escapeHtml(label)}</div><div class="kv-value">${value}</div></div>`;
}

async function loadDiagnostics() {
  const el = document.getElementById("diagnostics");
  try {
    const d = await Api.get("/api/diagnostics");
    const packages = Object.entries(d.packages).map(([k, v]) => `${escapeHtml(k)} ${escapeHtml(v)}`).join(" · ");
    const counts = Object.entries(d.counts).map(([k, v]) => `${escapeHtml(k.replace(/_/g, " "))}: ${v}`).join(" · ");
    el.innerHTML = `<div class="grid sm:grid-cols-3 gap-4">
      ${kv("Mode", d.mock_mode ? '<span class="badge badge-processing normal-case">Mock — no DeepSeek key</span>' : '<span class="badge badge-ready normal-case">DeepSeek connected</span>')}
      ${kv("DeepSeek", `${escapeHtml(d.deepseek.base_url)}<br><span class="text-xs text-gray-500">text ${escapeHtml(d.deepseek.text_model)} · vision ${escapeHtml(d.deepseek.vision_model)}</span>`)}
      ${kv("Log level", `${escapeHtml(d.log_level)} <span class="text-xs text-gray-500">(set LOG_LEVEL=DEBUG in .env, or start with --debug, for more detail)</span>`)}
      ${kv("Python", `${escapeHtml(d.python)}<br><span class="text-xs text-gray-500">${escapeHtml(d.platform)}</span>`)}
      ${kv("Packages", `<span class="text-xs">${packages}</span>`)}
      ${kv("Records", `<span class="text-xs">${counts}</span>`)}
      ${kv("Data folder", `<code>${escapeHtml(d.data_dir)}</code><br><span class="text-xs text-gray-500">${d.disk_free_gb} GB free</span>`)}
      ${kv("Database", `<code>${escapeHtml(d.database)}</code>`)}
      ${kv("Log file", `<code>${escapeHtml(d.log_file)}</code>`)}
    </div>`;
  } catch (e) {
    el.innerHTML = `<div class="callout callout-danger">Could not load diagnostics: ${escapeHtml(e.message)}</div>`;
  }
}

function levelBadge(level) {
  const cls = { ERROR: "badge-failed", CRITICAL: "badge-failed", WARNING: "badge-processing", INFO: "badge-source" }[level] || "";
  return `<span class="badge ${cls} normal-case">${escapeHtml(level)}</span>`;
}

async function loadLogs() {
  const query = new URLSearchParams({
    level: filters.level.value,
    limit: filters.limit.value,
    request_id: filters.request_id.value.trim(),
    q: filters.q.value.trim(),
  });
  try {
    const data = await Api.get(`/api/logs?${query}`);
    const entries = data.entries.slice().reverse(); // newest first
    summaryEl.textContent = `${entries.length} entr${entries.length === 1 ? "y" : "ies"} · newest first · ${data.log_file}`;
    rowsEl.innerHTML = entries.length
      ? entries
          .map(
            (e) => `<tr class="log-row log-${e.level.toLowerCase()}">
          <td class="whitespace-nowrap">${escapeHtml(e.time)}</td>
          <td>${levelBadge(e.level)}</td>
          <td class="whitespace-nowrap"><a href="#" class="ref-link" data-ref="${escapeHtml(e.request_id)}">${escapeHtml(e.request_id)}</a></td>
          <td class="text-xs text-gray-500">${escapeHtml(e.logger.replace(/^app\./, ""))}</td>
          <td><pre class="log-message">${escapeHtml(e.message)}</pre></td>
        </tr>`
          )
          .join("")
      : '<tr><td colspan="5" class="text-sm text-gray-500 p-4">No log entries match these filters.</td></tr>';
  } catch (e) {
    rowsEl.innerHTML = `<tr><td colspan="5"><div class="callout callout-danger">Could not load the log: ${escapeHtml(e.message)}</div></td></tr>`;
  }
}

rowsEl.addEventListener("click", (ev) => {
  const link = ev.target.closest(".ref-link");
  if (!link || link.dataset.ref === "-") return;
  ev.preventDefault();
  filters.request_id.value = link.dataset.ref;
  filters.level.value = "DEBUG";
  loadLogs();
});

filters.addEventListener("submit", (ev) => {
  ev.preventDefault();
  loadLogs();
});
document.getElementById("clear-filters").addEventListener("click", () => {
  filters.reset();
  filters.request_id.value = "";
  loadLogs();
});

setInterval(() => {
  if (autoRefresh.checked && document.visibilityState === "visible") loadLogs();
}, 3000);

loadDiagnostics();
loadLogs();
