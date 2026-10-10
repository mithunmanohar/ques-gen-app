// Renders the left sidebar into <aside id="sidebar"> on every page, so the
// navigation lives in one place. Load this before the page's own scripts.

const NAV_ICONS = {
  overview:
    '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  admin:
    '<path d="M4 20h16"/><path d="M12 15V4"/><path d="m7 9 5-5 5 5"/>',
  bank:
    '<path d="M4 5.5A1.5 1.5 0 0 1 5.5 4H9v16H5.5A1.5 1.5 0 0 1 4 18.5z"/><path d="M9 4h5.5A1.5 1.5 0 0 1 16 5.5V20H9"/><path d="m16 6 3.2-.9a1 1 0 0 1 1.2.7l3 11.5"/>',
  generate:
    '<path d="M14 3H6.5A1.5 1.5 0 0 0 5 4.5v15A1.5 1.5 0 0 0 6.5 21h11a1.5 1.5 0 0 0 1.5-1.5V8z"/><path d="M14 3v5h5"/><path d="M12 11v6"/><path d="M9 14h6"/>',
  evaluate:
    '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="m8.5 12 2.5 2.5 4.5-5"/>',
};

const NAV_SECTIONS = [
  { items: [{ href: "/index.html", label: "Overview", icon: "overview" }] },
  {
    label: "Content",
    items: [
      { href: "/admin.html", label: "Papers & patterns", icon: "admin" },
      { href: "/bank.html", label: "Question bank", icon: "bank" },
    ],
  },
  {
    label: "Practice",
    items: [
      { href: "/generate.html", label: "Question sets", icon: "generate", also: ["/set.html"] },
      { href: "/evaluate.html", label: "Submit & grade", icon: "evaluate" },
    ],
  },
];

function navIcon(name) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${NAV_ICONS[name]}</svg>`;
}

function renderSidebar() {
  const aside = document.getElementById("sidebar");
  if (!aside) return;
  const path = location.pathname === "/" ? "/index.html" : location.pathname;
  const sections = NAV_SECTIONS.map((section) => {
    const links = section.items
      .map((item) => {
        const active = item.href === path || (item.also || []).includes(path);
        return `<a class="sidebar-link${active ? " active" : ""}" href="${item.href}"${active ? ' aria-current="page"' : ""}>
          ${navIcon(item.icon)}<span>${item.label}</span></a>`;
      })
      .join("");
    return (section.label ? `<div class="sidebar-label">${section.label}</div>` : "") + links;
  }).join("");

  aside.innerHTML = `
    <div class="sidebar-brand">
      <div class="brand-mark">QS</div>
      <div>
        <div class="brand-name">Question Set Studio</div>
        <div class="brand-caption">Practice papers &amp; grading</div>
      </div>
    </div>
    <nav class="sidebar-nav" aria-label="Main">${sections}</nav>
    <div class="sidebar-footer">
      <div class="status-line"><span class="status-dot" id="status-dot"></span><span id="status-text">Checking…</span></div>
      <div class="status-hint" id="status-hint"></div>
    </div>`;

  fetch("/api/health")
    .then((r) => r.json())
    .then((h) => {
      document.getElementById("status-dot").classList.add(h.mock_mode ? "mock" : "live");
      document.getElementById("status-text").textContent = h.mock_mode ? "Mock mode" : "DeepSeek connected";
      document.getElementById("status-hint").textContent = h.mock_mode ? "Add DEEPSEEK_API_KEY to .env" : "";
    })
    .catch(() => {
      document.getElementById("status-dot").classList.add("down");
      document.getElementById("status-text").textContent = "Backend unreachable";
    });
}

renderSidebar();
