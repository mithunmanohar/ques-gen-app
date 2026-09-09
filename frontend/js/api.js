// Small fetch wrapper shared by every page. No build step, no framework —
// just plain JS so the app stays "clone it and run it" simple.

const Api = {
  async _handle(res) {
    if (!res.ok) {
      let detail = res.statusText;
      try {
        const body = await res.json();
        detail = body.detail ? JSON.stringify(body.detail) : JSON.stringify(body);
      } catch (_) {
        // response wasn't JSON; keep statusText
      }
      throw new Error(`${res.status}: ${detail}`);
    }
    if (res.status === 204) return null;
    return res.json();
  },

  get(url) {
    return fetch(url).then(this._handle);
  },
  postJson(url, body) {
    return fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(this._handle);
  },
  putJson(url, body) {
    return fetch(url, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    }).then(this._handle);
  },
  postForm(url, formData) {
    return fetch(url, { method: "POST", body: formData }).then(this._handle);
  },
  del(url) {
    return fetch(url, { method: "DELETE" }).then(this._handle);
  },
};

function toast(message, type = "success") {
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4500);
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str ?? "";
  return div.innerHTML;
}
