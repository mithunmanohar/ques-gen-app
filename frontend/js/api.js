// Small fetch wrapper shared by every page. No build step, no framework —
// just plain JS so the app stays "clone it and run it" simple.
//
// Every request carries an X-Request-ID. The server tags all its log lines
// with it, so a failing action can be traced in Logs & diagnostics, and the
// live log panel can follow a long-running request while it works.

class ApiError extends Error {
  constructor(status, body, requestId) {
    const detail = ApiError.describe(body);
    super(`${status ? status + ": " : ""}${detail}`);
    this.status = status;
    this.body = body || {};
    this.detail = detail;
    this.requestId = (body && body.request_id) || requestId || "";
    this.errorType = (body && body.error_type) || "";
    this.traceback = (body && body.traceback) || [];
  }

  static describe(body) {
    if (!body) return "No response from the server (is it still running?)";
    const d = body.detail;
    if (typeof d === "string") return d;
    if (Array.isArray(d)) {
      return d.map((e) => (e.loc ? `${e.loc.filter((p) => p !== "body").join(".")}: ${e.msg}` : JSON.stringify(e))).join("; ");
    }
    return JSON.stringify(d ?? body);
  }
}

const Api = {
  newRequestId() {
    return "ui-" + Math.random().toString(36).slice(2, 10);
  },

  async request(method, url, { body, json, requestId } = {}) {
    const id = requestId || Api.newRequestId();
    const headers = { "X-Request-ID": id };
    let payload = body;
    if (json !== undefined) {
      headers["Content-Type"] = "application/json";
      payload = JSON.stringify(json);
    }
    let res;
    try {
      res = await fetch(url, { method, headers, body: payload });
    } catch (networkError) {
      const err = new ApiError(0, { detail: `Could not reach the server: ${networkError.message}. Is the app still running?` }, id);
      console.error(`[${id}] ${method} ${url} — network error`, networkError);
      throw err;
    }
    const serverId = res.headers.get("X-Request-ID") || id;
    if (!res.ok) {
      let data = null;
      try {
        data = await res.json();
      } catch (_) {
        data = { detail: res.statusText || `HTTP ${res.status}` };
      }
      const err = new ApiError(res.status, data, serverId);
      console.error(`[${serverId}] ${method} ${url} failed with ${res.status}:`, data);
      throw err;
    }
    if (res.status === 204) return null;
    return res.json();
  },

  get(url, opts) {
    return Api.request("GET", url, opts);
  },
  postJson(url, json, opts = {}) {
    return Api.request("POST", url, { ...opts, json });
  },
  putJson(url, json, opts = {}) {
    return Api.request("PUT", url, { ...opts, json });
  },
  postForm(url, formData, opts = {}) {
    return Api.request("POST", url, { ...opts, body: formData });
  },
  del(url, opts) {
    return Api.request("DELETE", url, opts);
  },
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}

function toast(message, type = "success", { html = false, timeout } = {}) {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.innerHTML = `<div class="toast-body">${html ? message : escapeHtml(message)}</div><button class="toast-close" aria-label="Dismiss">×</button>`;
  el.querySelector(".toast-close").onclick = () => el.remove();
  document.body.appendChild(el);
  setTimeout(() => el.remove(), timeout ?? (type === "error" ? 15000 : 4500));
}

// Shows a failure with everything needed to debug it: the server's explanation,
// the error type, and a link to that request's full log.
function showError(e, context = "") {
  const err = e instanceof ApiError ? e : new ApiError(0, { detail: e && e.message ? e.message : String(e) });
  const ref = err.requestId
    ? `<div class="toast-meta">Ref ${escapeHtml(err.requestId)}${err.errorType ? " · " + escapeHtml(err.errorType) : ""} ·
         <a href="/logs.html?request_id=${encodeURIComponent(err.requestId)}" target="_blank">View log</a></div>`
    : "";
  toast(`${context ? `<strong>${escapeHtml(context)}</strong> ` : ""}${escapeHtml(err.detail || err.message)}${ref}`, "error", { html: true });
  if (err.traceback && err.traceback.length) console.error("Server traceback:\n" + err.traceback.join("\n"));
}

// A collapsible block for a stored processing log (import, generation, grading).
function renderLogLines(lines, title = "Processing log", open = false) {
  if (!lines || !lines.length) return "";
  const body = lines
    .map((line) => {
      const cls = /\bERROR\b|\bCRITICAL\b|Traceback/.test(line) ? "log-error" : /\bWARNING\b/.test(line) ? "log-warn" : "";
      return `<span class="${cls}">${escapeHtml(line)}</span>`;
    })
    .join("\n");
  const problems = lines.filter((l) => /\bWARNING\b|\bERROR\b/.test(l)).length;
  return `<details class="log-details"${open ? " open" : ""}>
    <summary>${escapeHtml(title)} · ${lines.length} line${lines.length === 1 ? "" : "s"}${problems ? ` · <span class="log-warn">${problems} warning/error</span>` : ""}</summary>
    <pre class="log-pre">${body}</pre>
  </details>`;
}

// Follows a running request's server log in `container` until stop() is called.
function startLiveLog(container, requestId, title = "Live log") {
  container.classList.remove("hidden");
  container.innerHTML = `<div class="live-log-head"><span class="live-dot"></span><span class="live-title">${escapeHtml(title)}</span>
    <a class="live-link" href="/logs.html?request_id=${encodeURIComponent(requestId)}" target="_blank">Ref ${escapeHtml(requestId)}</a></div>
    <pre class="log-pre live-pre">Waiting for the server…</pre>`;
  const pre = container.querySelector(".live-pre");
  let stopped = false;

  async function poll() {
    try {
      const data = await Api.get(`/api/logs?request_id=${encodeURIComponent(requestId)}&level=INFO&limit=400`);
      const lines = data.entries.map((e) => {
        const cls = e.level === "ERROR" || e.level === "CRITICAL" ? "log-error" : e.level === "WARNING" ? "log-warn" : "";
        return `<span class="${cls}">${escapeHtml(e.time.slice(11))} ${escapeHtml(e.level.padEnd(7))} ${escapeHtml(e.message)}</span>`;
      });
      if (lines.length) {
        pre.innerHTML = lines.join("\n");
        pre.scrollTop = pre.scrollHeight;
      }
    } catch (_) {
      // The log endpoint itself failing shouldn't interrupt the real action.
    }
  }

  const timer = setInterval(() => !stopped && poll(), 1000);
  poll();
  return async function stop(ok = true) {
    stopped = true;
    clearInterval(timer);
    await poll();
    container.querySelector(".live-dot").classList.add(ok ? "done" : "failed");
    container.querySelector(".live-title").textContent = `${title} — ${ok ? "finished" : "failed"}`;
  };
}

window.addEventListener("error", (ev) => console.error("Page error:", ev.error || ev.message));
window.addEventListener("unhandledrejection", (ev) => {
  console.error("Unhandled promise rejection:", ev.reason);
  if (ev.reason instanceof ApiError) showError(ev.reason);
});
