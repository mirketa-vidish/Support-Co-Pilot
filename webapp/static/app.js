const state = {
  projects: [],
  currentProjectId: null,
  currentProjectDetail: null,
  casesInProject: [],
};

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str == null ? "" : String(str);
  return div.innerHTML;
}

function showResult(box, ok, message) {
  box.classList.remove("hidden");
  box.className = "result-box " + (ok ? "ok" : "err");
  box.textContent = message;
}

async function parseErrorResponse(res) {
  try {
    const data = await res.json();
    return data.detail || JSON.stringify(data);
  } catch {
    return `Request failed (HTTP ${res.status})`;
  }
}

// ================= Navigation =================

function showProjectsView() {
  document.getElementById("view-projects").classList.add("active");
  document.getElementById("view-project").classList.remove("active");
  state.currentProjectId = null;
  loadProjects();
}

function showProjectView(projectId) {
  state.currentProjectId = projectId;
  document.getElementById("view-projects").classList.remove("active");
  document.getElementById("view-project").classList.add("active");
  document.getElementById("project-title").textContent = projectId;
  switchProjectTab("overview");
  loadProjectDetail();
  loadCasesInProject();
  document.getElementById("chat-log").innerHTML =
    '<div class="chat-empty">Ask a question to start investigating.</div>';
}

function switchProjectTab(tab) {
  document.querySelectorAll("#view-project .tab-btn").forEach((b) => {
    b.classList.toggle("active", b.dataset.ptab === tab);
  });
  document.querySelectorAll("#view-project .ptab").forEach((s) => {
    s.classList.toggle("active", s.id === `ptab-${tab}`);
  });
  if (tab === "investigate") loadCurrentModel();
}

document.querySelectorAll("#view-project .tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => switchProjectTab(btn.dataset.ptab));
});

document.getElementById("back-to-projects").addEventListener("click", showProjectsView);

// ================= Projects list =================

async function loadProjects() {
  const res = await fetch("/api/projects");
  const projects = await res.json();
  state.projects = projects;

  const list = document.getElementById("projects-list");
  const empty = document.getElementById("projects-empty");
  list.innerHTML = "";
  empty.classList.toggle("hidden", projects.length > 0);

  for (const p of projects) {
    const card = document.createElement("div");
    card.className = "case-card";
    const codeCount = p.doc_types.code || 0;
    const sddCount = p.doc_types.sdd || 0;
    card.innerHTML = `
      <div class="case-id">${escapeHtml(p.project_id)}</div>
      <div class="customer">${p.case_count} case(s)</div>
      <div class="doc-type-pills">
        <span class="doc-pill">code: ${codeCount}</span>
        <span class="doc-pill">sdd: ${sddCount}</span>
      </div>
    `;
    card.addEventListener("click", () => showProjectView(p.project_id));
    list.appendChild(card);
  }
}

document.getElementById("show-create-project").addEventListener("click", () => {
  document.getElementById("create-project-panel").classList.toggle("hidden");
});
document.getElementById("cancel-create-project").addEventListener("click", () => {
  document.getElementById("create-project-panel").classList.add("hidden");
});

document.getElementById("create-project-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const submitBtn = document.getElementById("create-project-submit");
  const resultBox = document.getElementById("create-project-result");
  submitBtn.disabled = true;
  submitBtn.textContent = "Creating...";
  resultBox.classList.add("hidden");

  try {
    const res = await fetch("/api/projects", { method: "POST", body: new FormData(form) });
    if (!res.ok) {
      showResult(resultBox, false, await parseErrorResponse(res));
      return;
    }
    const data = await res.json();
    form.reset();
    document.getElementById("create-project-panel").classList.add("hidden");
    await loadProjects();
    showProjectView(data.project.project_id);
  } catch (err) {
    showResult(resultBox, false, `Request failed: ${err}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Create project";
  }
});

// ================= Project overview =================

async function loadProjectDetail() {
  const projectId = state.currentProjectId;
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}`);
  if (!res.ok) return;
  const data = await res.json();
  state.currentProjectDetail = data;

  const codeCount = data.doc_types.code || 0;
  const sddCount = data.doc_types.sdd || 0;

  document.getElementById("project-stats").innerHTML = `
    <div class="stat-tile"><div class="value">${data.code_files.length}</div><div class="label">Code files</div></div>
    <div class="stat-tile"><div class="value">${codeCount}</div><div class="label">Code chunks</div></div>
    <div class="stat-tile"><div class="value">${sddCount}</div><div class="label">SDD chunks</div></div>
    <div class="stat-tile"><div class="value">${data.case_count}</div><div class="label">Cases</div></div>
  `;

  const fileList = document.getElementById("project-file-list");
  fileList.innerHTML = data.code_files.length
    ? data.code_files.map((f) => `<div class="file-list-item" data-path="${escapeHtml(f)}">${escapeHtml(f)}</div>`).join("")
    : '<div class="file-list-item">No code indexed.</div>';
  fileList.querySelectorAll(".file-list-item[data-path]").forEach((el) => {
    el.addEventListener("click", () => loadProjectFile(el.dataset.path));
  });

  const sddStatus = document.getElementById("sdd-status");
  sddStatus.textContent = sddCount > 0
    ? `SDD indexed (${sddCount} chunk(s)).`
    : "No implementation document uploaded yet (optional).";

  const overrideRow = document.getElementById("sdd-override-row");
  const overrideCheckbox = overrideRow.querySelector("input[name=confirm_override]");
  overrideRow.classList.toggle("hidden", sddCount === 0);
  overrideCheckbox.required = sddCount > 0;
}

async function loadProjectFile(path) {
  const viewer = document.getElementById("project-code-viewer");
  viewer.classList.remove("hidden");
  viewer.textContent = "Loading...";
  const res = await fetch(`/api/projects/${encodeURIComponent(state.currentProjectId)}/file?path=${encodeURIComponent(path)}`);
  if (!res.ok) {
    viewer.textContent = "Failed to load file.";
    return;
  }
  const data = await res.json();
  viewer.textContent = data.content;
}

function wirePanelToggle(showBtnId, panelId) {
  document.getElementById(showBtnId).addEventListener("click", () => {
    document.getElementById(panelId).classList.toggle("hidden");
  });
}
wirePanelToggle("show-update-code", "update-code-panel");
wirePanelToggle("show-update-sdd", "update-sdd-panel");

document.querySelectorAll(".cancel-panel").forEach((btn) => {
  btn.addEventListener("click", () => btn.closest(".panel").classList.add("hidden"));
});

document.getElementById("update-code-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const resultBox = form.nextElementSibling;
  const submitBtn = form.querySelector("button[type=submit]");
  submitBtn.disabled = true;
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(state.currentProjectId)}/code`, {
      method: "POST",
      body: new FormData(form),
    });
    if (!res.ok) {
      showResult(resultBox, false, await parseErrorResponse(res));
      return;
    }
    const data = await res.json();
    showResult(resultBox, true, `Code replaced: ${data.chunks_indexed} chunk(s) indexed.`);
    form.reset();
    await loadProjectDetail();
  } catch (err) {
    showResult(resultBox, false, `Request failed: ${err}`);
  } finally {
    submitBtn.disabled = false;
  }
});

document.getElementById("update-sdd-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const form = e.target;
  const resultBox = form.nextElementSibling;
  const submitBtn = form.querySelector("button[type=submit]");
  submitBtn.disabled = true;
  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(state.currentProjectId)}/sdd`, {
      method: "POST",
      body: new FormData(form),
    });
    if (!res.ok) {
      showResult(resultBox, false, await parseErrorResponse(res));
      return;
    }
    const data = await res.json();
    showResult(resultBox, true, `SDD saved: ${data.chunks_indexed} chunk(s) indexed.`);
    form.reset();
    await loadProjectDetail();
  } catch (err) {
    showResult(resultBox, false, `Request failed: ${err}`);
  } finally {
    submitBtn.disabled = false;
  }
});

// ================= Cases =================

async function loadCasesInProject() {
  const projectId = state.currentProjectId;
  const res = await fetch(`/api/projects/${encodeURIComponent(projectId)}/cases`);
  const cases = res.ok ? await res.json() : [];
  state.casesInProject = cases;

  const list = document.getElementById("cases-in-project-list");
  const empty = document.getElementById("cases-empty");
  list.innerHTML = "";
  empty.classList.toggle("hidden", cases.length > 0);
  document.getElementById("case-detail").classList.add("hidden");

  for (const c of cases) {
    const card = document.createElement("div");
    card.className = "case-card";
    const pills = Object.entries(c.doc_types)
      .map(([type, count]) => `<span class="doc-pill">${escapeHtml(type)}: ${count}</span>`)
      .join("");
    card.innerHTML = `<div class="case-id">${escapeHtml(c.case_id)}</div><div class="doc-type-pills">${pills}</div>`;
    card.addEventListener("click", () => loadCaseDetail(c.case_id));
    list.appendChild(card);
  }

  renderChatCaseOptions();
}

async function loadCaseDetail(caseId) {
  const detail = document.getElementById("case-detail");
  detail.classList.remove("hidden");
  detail.innerHTML = `<div class="empty-state">Loading ${escapeHtml(caseId)}...</div>`;

  const res = await fetch(`/api/projects/${encodeURIComponent(state.currentProjectId)}/cases/${encodeURIComponent(caseId)}`);
  if (!res.ok) {
    detail.innerHTML = `<div class="empty-state">Failed to load case detail.</div>`;
    return;
  }
  const data = await res.json();
  const s = data.log_signals;
  const statTiles = s
    ? `
    <div class="stat-row">
      <div class="stat-tile"><div class="value">${s.exceptions.length}</div><div class="label">Exceptions</div></div>
      <div class="stat-tile"><div class="value">${s.fatal_errors.length}</div><div class="label">Fatal errors</div></div>
      <div class="stat-tile"><div class="value">${s.dml_statement_count}</div><div class="label">DML statements</div></div>
      <div class="stat-tile"><div class="value">${s.soql_query_count}</div><div class="label">SOQL queries</div></div>
      <div class="stat-tile"><div class="value">${s.total_lines.toLocaleString()}</div><div class="label">Log lines</div></div>
      ${s.log_count > 1 ? `<div class="stat-tile"><div class="value">${s.log_count}</div><div class="label">Debug logs</div></div>` : ""}
    </div>
    ${s.log_count === 1 && s.log_file ? `<p class="hint">Debug log: ${escapeHtml(s.log_file)}</p>` : ""}
    ${s.logs ? `<div class="detail-section"><h3>Debug logs</h3><div class="line-list">${s.logs.map((l) => `<div>${escapeHtml(l.log_file)} &mdash; ${l.total_lines.toLocaleString()} lines, ${l.exception_count} exception(s), ${l.fatal_error_count} fatal error(s), ${l.dml_statement_count} DML, ${l.soql_query_count} SOQL</div>`).join("")}</div></div>` : ""}
    ${s.exceptions.length ? `<div class="detail-section"><h3>Exceptions</h3><div class="line-list">${s.exceptions.map((l) => `<div>${escapeHtml(l)}</div>`).join("")}</div></div>` : ""}
    ${s.fatal_errors.length ? `<div class="detail-section"><h3>Fatal errors</h3><div class="line-list">${s.fatal_errors.map((l) => `<div>${escapeHtml(l)}</div>`).join("")}</div></div>` : ""}
  `
    : `<p class="hint">No debug log indexed for this case.</p>`;

  detail.innerHTML = `
    <h2>${escapeHtml(data.case_id)}</h2>
    ${statTiles}
    <div class="detail-section">
      <button class="btn-primary" id="investigate-this-case">Investigate this case &rarr;</button>
    </div>
  `;
  document.getElementById("investigate-this-case").addEventListener("click", () => {
    switchProjectTab("investigate");
    document.getElementById("chat-case-select").value = data.case_id;
  });
}

// Debug logs must be .log files. The `accept=".log"` attribute only pre-filters the file dialog -
// the user can still switch it to "All files" or drag a file onto the input - so reject any other
// file the moment it's selected, and re-check on submit. The server enforces the same rule.
const caseLogInput = document.getElementById("c-log");

function nonLogFiles(input) {
  return Array.from(input.files).filter((f) => !f.name.toLowerCase().endsWith(".log"));
}

function rejectNonLogFiles(input) {
  const bad = nonLogFiles(input);
  if (!bad.length) return false;
  input.value = "";
  showResult(
    document.getElementById("new-case-result"),
    false,
    `Only .log files are allowed. Not accepted: ${bad.map((f) => f.name).join(", ")}`,
  );
  return true;
}

caseLogInput.addEventListener("change", () => {
  if (!rejectNonLogFiles(caseLogInput)) {
    document.getElementById("new-case-result").classList.add("hidden");
  }
});

document.getElementById("new-case-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (rejectNonLogFiles(caseLogInput)) return;
  const form = e.target;
  const submitBtn = document.getElementById("new-case-submit");
  const resultBox = document.getElementById("new-case-result");
  submitBtn.disabled = true;
  submitBtn.textContent = "Creating...";
  resultBox.classList.add("hidden");

  try {
    const res = await fetch(`/api/projects/${encodeURIComponent(state.currentProjectId)}/cases`, {
      method: "POST",
      body: new FormData(form),
    });
    if (!res.ok) {
      showResult(resultBox, false, await parseErrorResponse(res));
      return;
    }
    const data = await res.json();
    const docTypes = Object.entries(data.case.doc_types).map(([t, n]) => `${t}: ${n}`).join(", ");
    showResult(resultBox, true, `Created case ${data.case.case_id} — ${docTypes}`);
    form.reset();
    await loadCasesInProject();
    await loadProjectDetail();
  } catch (err) {
    showResult(resultBox, false, `Request failed: ${err}`);
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Create case";
  }
});

// ================= Investigate / chat =================

function renderChatCaseOptions() {
  const select = document.getElementById("chat-case-select");
  const current = select.value;
  select.innerHTML = '<option value="">— none, project-wide —</option>';
  for (const c of state.casesInProject) {
    const opt = document.createElement("option");
    opt.value = c.case_id;
    opt.textContent = c.case_id;
    select.appendChild(opt);
  }
  select.value = current;
}

const chatForm = document.getElementById("chat-form");
const chatLog = document.getElementById("chat-log");

// AI model picker. The server reports every provider with a live readiness status (API key
// checked, daily limit not reached); unusable ones are listed but disabled with the reason.
// The user's pick is kept while it stays ready; otherwise the server's default (Groq when its
// key works) is selected. Whatever is picked is only tried first - if it fails mid-
// investigation, the server still switches to the other model and says so in a notice.
const modelSelect = document.getElementById("model-select");
let userPickedProvider = null;

modelSelect.addEventListener("change", () => {
  userPickedProvider = modelSelect.value || null;
});

function renderCurrentModel(info) {
  if (!info || !info.providers) return;
  const note = document.getElementById("model-note");
  modelSelect.innerHTML = "";
  for (const p of info.providers) {
    const opt = document.createElement("option");
    opt.value = p.provider;
    opt.disabled = !p.ready;
    opt.textContent = `${p.label} · ${p.model}` + (p.ready ? "" : ` — ${p.status}`);
    modelSelect.appendChild(opt);
  }
  const readyIds = info.providers.filter((p) => p.ready).map((p) => p.provider);
  if (readyIds.length === 0) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "No AI model available";
    modelSelect.insertBefore(opt, modelSelect.firstChild);
    modelSelect.value = "";
  } else {
    modelSelect.value = readyIds.includes(userPickedProvider) ? userPickedProvider : info.default;
  }
  // Amber = the usual default (Groq) isn't usable right now - not merely "user chose Gemini".
  modelSelect.classList.toggle("fallback", !readyIds.includes("groq"));
  note.textContent = info.note || "";
  note.classList.toggle("hidden", !info.note);
}

async function loadCurrentModel() {
  try {
    const res = await fetch("/api/model");
    if (res.ok) renderCurrentModel(await res.json());
  } catch (_) {
    modelSelect.innerHTML = '<option value="">Unavailable (server not reachable)</option>';
  }
}

function prependNotices(wrap, notices) {
  for (const text of notices || []) {
    const div = document.createElement("div");
    div.className = "msg-notice";
    div.textContent = `⚠ ${text}`;
    wrap.insertBefore(div, wrap.firstChild);
  }
}

function appendModelMeta(wrap, data) {
  if (!data.provider_label) return;
  const meta = document.createElement("div");
  meta.className = "msg-meta";
  meta.textContent = `${data.error ? "Error from" : "Response from"} ${data.provider_label} · ${data.model}`;
  wrap.appendChild(meta);
}

function appendMessage(role, text, isError = false) {
  const empty = chatLog.querySelector(".chat-empty");
  if (empty) empty.remove();

  const wrap = document.createElement("div");
  wrap.className = `msg msg-${role}`;
  const bubble = document.createElement("div");
  bubble.className = "msg-bubble" + (isError ? " err" : "");
  bubble.textContent = text;
  wrap.appendChild(bubble);
  chatLog.appendChild(wrap);
  chatLog.scrollTop = chatLog.scrollHeight;
  return wrap;
}

function appendTrace(wrap, trace) {
  if (!trace || trace.length === 0) return;
  const details = document.createElement("details");
  details.className = "trace";
  const summary = document.createElement("summary");
  summary.textContent = `${trace.length} tool call(s)`;
  details.appendChild(summary);
  for (const step of trace) {
    const div = document.createElement("div");
    div.className = "trace-call";
    const resultText = JSON.stringify(step.result);
    const preview = resultText.length > 400 ? resultText.slice(0, 400) + "...(truncated)" : resultText;
    div.textContent = `${step.tool}(${JSON.stringify(step.args)})\n-> ${preview}`;
    details.appendChild(div);
  }
  wrap.appendChild(details);
}

chatForm.addEventListener("submit", async (e) => {
  e.preventDefault();
  const textarea = document.getElementById("chat-question");
  const question = textarea.value.trim();
  if (!question) return;

  const caseId = document.getElementById("chat-case-select").value || null;
  appendMessage("user", question);
  textarea.value = "";

  const sendBtn = document.getElementById("chat-send");
  sendBtn.disabled = true;
  const typing = document.createElement("div");
  typing.className = "typing";
  typing.textContent = "Investigating...";
  chatLog.appendChild(typing);
  chatLog.scrollTop = chatLog.scrollHeight;

  try {
    const res = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        project_id: state.currentProjectId,
        case_id: caseId,
        provider: modelSelect.value || null,
      }),
    });
    const data = await res.json();
    typing.remove();

    if (!res.ok) {
      appendMessage("assistant", data.detail || "Request failed.", true);
      return;
    }
    renderCurrentModel(data.current_model);
    const wrap = data.error
      ? appendMessage("assistant", `[${data.error}]`, true)
      : appendMessage("assistant", data.answer || "(no answer)");
    prependNotices(wrap, data.notices);
    appendModelMeta(wrap, data);
    appendTrace(wrap, data.trace);
  } catch (err) {
    typing.remove();
    appendMessage("assistant", `Request failed: ${err}`, true);
  } finally {
    sendBtn.disabled = false;
  }
});

// ================= Init =================
showProjectsView();
