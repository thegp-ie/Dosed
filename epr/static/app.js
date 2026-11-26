/* Dosed EPR — browser client. No framework, no third-party CDN (CSP 'self' only).
 * All text goes through textContent (via h()) so patient data can never inject HTML. */
"use strict";

const S = { me: null, csrf: "", view: "today", chart: null, tab: "summary", users: [], idleTimer: null };
const $app = () => document.getElementById("app");

// ------------------------------------------------------------------ helpers
function h(tag, attrs, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === null || v === undefined || v === false) continue;
    if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = v;
    else if (k === "value") el.value = v;
    else if (k === "checked") el.checked = !!v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
const fmtDate = (s) => (s ? new Date(s.length === 10 ? s + "T00:00:00" : s).toLocaleDateString("en-IE") : "");
const fmtDT = (s) => (s ? new Date(s).toLocaleString("en-IE", { dateStyle: "short", timeStyle: "short" }) : "");
const can = (p) => S.me && S.me.permissions.includes(p);
const userName = (id) => (S.users.find((u) => u.id === id) || {}).full_name || "";

function toast(msg) {
  const t = document.getElementById("toast");
  t.textContent = msg;
  t.classList.add("show");
  clearTimeout(t._h);
  t._h = setTimeout(() => t.classList.remove("show"), 3500);
}

async function api(method, url, body, opts = {}) {
  const init = { method, headers: {}, credentials: "same-origin" };
  if (method !== "GET") init.headers["X-EPR-CSRF"] = S.csrf;
  if (body instanceof FormData) init.body = body;
  else if (body !== undefined) { init.headers["Content-Type"] = "application/json"; init.body = JSON.stringify(body); }
  const r = await fetch(url, init);
  if (r.status === 401 && !opts.allow401) { S.me = null; renderLogin("Your session has ended. Please sign in again."); throw new Error("signed out"); }
  if (opts.raw) return r;
  const data = r.headers.get("content-type")?.includes("json") ? await r.json() : await r.text();
  if (!r.ok) { const msg = (data && data.detail) || r.statusText; toast(msg); throw new Error(msg); }
  return data;
}

function form(fields, values = {}) {
  // fields: [name, label, type?, options?]
  return h("div", { class: "form" }, fields.map(([name, label, type = "text", opts]) => {
    const v = values[name] ?? "";
    let input;
    if (type === "select") input = h("select", { name }, opts.map((o) => { const [val, lab] = Array.isArray(o) ? o : [o, o]; return h("option", { value: val, selected: String(v) === String(val) }, lab); }));
    else if (type === "textarea") input = h("textarea", { name, value: v });
    else if (type === "checkbox") return h("label", { class: "inline" }, h("input", { type: "checkbox", name, checked: !!v }), label);
    else input = h("input", { name, type, value: v });
    return h("label", { class: type === "textarea" ? "wide" : "" }, label, input);
  }));
}
function readForm(root) {
  const out = {};
  root.querySelectorAll("input,select,textarea").forEach((el) => {
    if (!el.name) return;
    out[el.name] = el.type === "checkbox" ? el.checked : el.value.trim() === "" ? null : el.value.trim();
  });
  return out;
}
function card(title, actions, ...body) { return h("div", { class: "card" }, h("h3", {}, h("span", {}, title), h("span", { class: "row" }, actions)), body); }
function btn(label, onclick, cls = "") { return h("button", { class: "btn " + cls, onclick }, label); }
function table(cols, rows, onRow, rowClass) {
  return h("table", {}, h("thead", {}, h("tr", {}, cols.map((c) => h("th", {}, c[0])))),
    h("tbody", {}, rows.length ? rows.map((r) => h("tr", { class: (onRow ? "click " : "") + (rowClass ? rowClass(r) : ""), onclick: onRow ? () => onRow(r) : null },
      cols.map((c) => h("td", {}, c[1](r))))) : h("tr", {}, h("td", { colspan: cols.length, class: "muted" }, "Nothing to show"))));
}

// --------------------------------------------------------------- idle lock
function resetIdle() {
  if (!S.me) return;
  clearTimeout(S.idleTimer);
  S.idleTimer = setTimeout(async () => { try { await api("POST", "/api/auth/logout"); } catch (e) {} S.me = null; renderLogin("Signed out after inactivity."); }, (S.me.idle_minutes || 15) * 60 * 1000);
}
["click", "keydown"].forEach((ev) => document.addEventListener(ev, resetIdle, { passive: true }));

// --------------------------------------------------------------- sign-in
function renderLogin(msg) {
  const f = h("form", {}, h("label", {}, "Username", h("input", { name: "username", autocomplete: "username", required: true })),
    h("label", {}, "Password", h("input", { name: "password", type: "password", autocomplete: "current-password", required: true })),
    h("p", {}, h("button", { class: "btn", type: "submit" }, "Sign in")));
  f.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const me = await api("POST", "/api/auth/login", readForm(f), { allow401: true });
      S.csrf = me.csrf;
      if (me.mfa_passed) return start(me);
      renderMfa(me);
    } catch (err) {}
  });
  $app().replaceChildren(h("div", { class: "login" }, h("div", { class: "card" }, h("h2", {}, "Dosed EPR"), msg ? h("div", { class: "alert warn" }, msg) : null, f,
    h("p", { class: "small muted" }, "Authorised practice staff only. All access to patient records is logged."))));
  f.querySelector("input").focus();
}

async function renderMfa(me) {
  const box = h("div", { class: "card" }, h("h2", {}, "Two-factor authentication"));
  if (!me.user.mfa_enabled) {
    const setup = await api("POST", "/api/auth/mfa/setup");
    const canvas = h("canvas", {});
    if (window.QRCode) window.QRCode.toCanvas(canvas, setup.otpauth_uri, { width: 200 }, () => {});
    box.append(h("p", {}, "Scan this with an authenticator app (e.g. Microsoft Authenticator, Google Authenticator), then enter the 6-digit code."),
      h("div", { class: "qr" }, canvas), h("p", { class: "small muted" }, "Or enter this key: ", h("code", {}, setup.secret)));
  } else box.append(h("p", {}, "Enter the 6-digit code from your authenticator app."));
  const f = h("form", {}, h("label", {}, "Code", h("input", { name: "code", inputmode: "numeric", autocomplete: "one-time-code", maxlength: 6, required: true })), h("p", {}, h("button", { class: "btn" }, "Verify")));
  f.addEventListener("submit", async (e) => { e.preventDefault(); try { start(await api("POST", "/api/auth/mfa/verify", readForm(f), { allow401: true })); } catch (err) {} });
  box.append(f);
  $app().replaceChildren(h("div", { class: "login" }, box));
  f.querySelector("input").focus();
}

async function start(me) {
  S.me = me; S.csrf = me.csrf;
  S.users = await api("GET", "/api/auth/users");
  resetIdle();
  go("today");
}

// --------------------------------------------------------------- layout
const NAV = [
  ["today", "Today", null, "appointment.read"], ["patients", "Patients", null, "patient.read"],
  ["inbox", "Inbox", null, "inbox.read"], ["tasks", "Tasks", null, "tasks"], ["reports", "Reports", null, "reports"],
  ["governance", "Data protection", null, "governance"], ["settings", "My settings", null, null],
];
function layout(content) {
  const nav = h("nav", { class: "side", "aria-label": "Main" }, h("div", { class: "brand" }, "Dosed EPR", h("small", {}, S.me.practice.name)),
    NAV.filter((n) => !n[3] || can(n[3])).map(([k, label]) => h("button", { class: S.view === k ? "active" : "", onclick: () => go(k) }, label)),
    S.chart ? h("button", { class: S.view === "chart" ? "active" : "", onclick: () => go("chart") }, "↳ " + S.chart.patient.last_name) : null,
    h("div", { class: "spacer" }), h("div", { class: "who" }, S.me.user.full_name, h("br"), S.me.user.role.replace("_", " ")),
    h("button", { onclick: async () => { await api("POST", "/api/auth/logout"); S.me = null; S.chart = null; renderLogin("Signed out."); } }, "Sign out"));
  $app().replaceChildren(h("div", { class: "shell" }, nav, h("main", { id: "main" }, content)));
}
async function go(view) {
  S.view = view;
  const views = { today: viewToday, patients: viewPatients, chart: viewChart, inbox: viewInbox, tasks: viewTasks, reports: viewReports, governance: viewGovernance, settings: viewSettings };
  layout(h("p", { class: "muted" }, "Loading…"));
  try { layout(await views[view]()); } catch (e) { if (S.me) layout(h("div", { class: "alert bad" }, e.message)); }
}

// keyboard shortcuts: "/" search, Alt+C consult, Alt+P prescribe, Alt+I inbox, Alt+T today
document.addEventListener("keydown", (e) => {
  if (!S.me) return;
  const typing = ["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement?.tagName);
  if (e.key === "/" && !typing) { e.preventDefault(); go("patients"); }
  if (e.altKey && e.key.toLowerCase() === "i") { e.preventDefault(); go("inbox"); }
  if (e.altKey && e.key.toLowerCase() === "t") { e.preventDefault(); go("today"); }
  if (e.altKey && e.key.toLowerCase() === "c" && S.chart) { e.preventDefault(); S.tab = "consult"; go("chart"); }
  if (e.altKey && e.key.toLowerCase() === "p" && S.chart) { e.preventDefault(); S.tab = "prescribe"; go("chart"); }
});

// --------------------------------------------------------------- today
async function viewToday() {
  const day = new Date().toISOString().slice(0, 10);
  const appts = await api("GET", `/api/appointments?day=${day}`);
  return h("div", {}, h("h2", {}, "Today"),
    card("Appointments " + fmtDate(day), null, table([
      ["Time", (a) => new Date(a.start).toLocaleTimeString("en-IE", { timeStyle: "short" })],
      ["Patient", (a) => a.patient_name], ["With", (a) => a.clinician_name],
      ["Type", (a) => h("span", { class: "pill" + (a.mode === "video" ? " warn" : "") }, a.mode)],
      ["Status", (a) => a.status],
      ["", (a) => h("span", { class: "row" },
        a.mode === "video" && can("telehealth.host") ? btn("Start video", async (ev) => { ev.stopPropagation(); await startVideo(a); }) : null,
        a.status === "booked" ? btn("Arrived", async (ev) => { ev.stopPropagation(); await api("POST", `/api/appointments/${a.id}/status`, { status: "arrived" }); go("today"); }, "secondary") : null)],
    ], appts, (a) => openChart(a.patient_id))),
    h("p", { class: "small muted" }, "Shortcuts: ", h("kbd", {}, "/"), " find patient · ", h("kbd", {}, "Alt+C"), " new consultation · ", h("kbd", {}, "Alt+P"), " prescribe · ", h("kbd", {}, "Alt+I"), " inbox"));
}
async function startVideo(a) {
  const r = await api("POST", `/api/appointments/${a.id}/video`);
  window.open(r.clinician_url, "_blank", "noopener");
  await openChart(a.patient_id, "consult");
  const main = document.getElementById("main");
  main.prepend(card("Video consultation started", null,
    h("p", {}, "Send the patient this link by SMS or email (expires ", fmtDT(r.expires), "):"),
    h("div", { class: "row" }, h("input", { value: r.patient_url, readonly: true, size: 50 }), btn("Copy", () => { navigator.clipboard.writeText(r.patient_url); toast("Link copied"); }, "secondary")),
    h("p", { class: "small muted" }, "Before you sign the note: confirm the patient's identity and record their consent to a remote consultation.")));
}

// --------------------------------------------------------------- patients
async function viewPatients() {
  const results = h("div", {});
  const q = h("input", { placeholder: "Name, DOB (dd/mm/yyyy), GMS no., PPSN or chart no.", size: 48, "aria-label": "Search patients" });
  let t;
  const search = async () => {
    const rows = await api("GET", "/api/patients?q=" + encodeURIComponent(q.value));
    results.replaceChildren(table([["Name", (p) => `${p.last_name}, ${p.first_name}`], ["DOB", (p) => `${fmtDate(p.dob)} (${p.age})`],
      ["Address", (p) => [p.address1, p.town].filter(Boolean).join(", ")], ["Type", (p) => p.eligibility.toUpperCase()], ["IHI", (p) => p.ihi_display || ""]],
      rows, (p) => openChart(p.id)));
  };
  q.addEventListener("input", () => { clearTimeout(t); t = setTimeout(search, 200); });
  q.addEventListener("keydown", (e) => { if (e.key === "Enter") results.querySelector("tr.click")?.click(); });
  setTimeout(() => q.focus(), 0);
  search();
  const newForm = patientForm({});
  return h("div", {}, h("h2", {}, "Patients"), card("Find a patient", null, q, results),
    can("patient.write") ? card("Register a new patient", null, h("p", { class: "small muted" }, "Required: surname, first name, date of birth, gender, two address lines, registered GP."), newForm,
      h("p", {}, btn("Register", async () => { const p = await api("POST", "/api/patients", cleanPatient(readForm(newForm))); toast("Patient registered"); openChart(p.id); }))) : null,
    can("patient.ppsn") ? card("Import GMS panel (PCRS patient listing CSV)", null, pcrsImport()) : null);
}
function gpOptions() { return [["", "—"], ...S.users.filter((u) => ["gp"].includes(u.role) && u.active).map((u) => [u.id, u.full_name])]; }
function patientForm(p) {
  const f = [
    ["title", "Title"], ["first_name", "First name *"], ["middle_name", "Middle name"], ["last_name", "Surname *"],
    ["dob", "Date of birth *", "date"], ["sex", "Gender *", "select", [["", "—"], "female", "male", "other", "unknown"]],
    ["address1", "Address line 1 *"], ["address2", "Address line 2 *"], ["town", "Town/city"], ["county", "County"], ["eircode", "Eircode"],
    ["phone_mobile", "Mobile"], ["phone_home", "Home phone"], ["email", "Email"],
    ["registered_gp_id", "Registered GP *", "select", gpOptions()], ["usual_gp_id", "Usual GP", "select", gpOptions()],
    ["eligibility", "Patient type", "select", [["private", "Private"], ["gms", "GMS medical card"], ["dvc", "GP visit card"], ["other", "Other"]]],
    ["gms_number", "GMS / GPVC number"], ["gms_expiry", "Card expiry", "date"],
    ["ethnicity", "Ethnicity", "select", ["", "White Irish", "Irish Traveller", "Other White", "Black Irish or African", "Other Black", "Chinese", "Other Asian", "Other", "Not stated"]],
    ["preferred_language", "Preferred language"], ["interpreter_required", "Interpreter required", "checkbox"],
    ["nok_name", "Next of kin"], ["nok_relationship", "NOK relationship"], ["nok_phone", "NOK phone"],
    ["preferred_pharmacy", "Pharmacy"], ["preferred_pharmacy_healthmail", "Pharmacy Healthmail"],
    ["consent_sms", "Consents to SMS", "checkbox"], ["consent_email", "Consents to email", "checkbox"], ["consent_video", "Consents to video consultations", "checkbox"],
  ];
  if (can("patient.ppsn")) f.splice(6, 0, ["ppsn", "PPSN"], ["ihi", "IHI (18 digits)"]);
  return form(f, p);
}
function cleanPatient(d) { for (const k of ["registered_gp_id", "usual_gp_id"]) if (d[k]) d[k] = Number(d[k]); if (d.eligibility === null) delete d.eligibility; return d; }
function pcrsImport() {
  const file = h("input", { type: "file", accept: ".csv" });
  return h("div", { class: "row" }, file, btn("Import", async () => {
    if (!file.files[0]) return toast("Choose the CSV downloaded from the PCRS portal");
    const fd = new FormData(); fd.append("file", file.files[0]);
    const r = await api("POST", "/api/patients/import/pcrs-listing", fd);
    toast(`Created ${r.created}, updated ${r.updated}, skipped ${r.skipped}`);
  }, "secondary"));
}

// --------------------------------------------------------------- chart
async function openChart(id, tab = "summary") { S.chart = await api("GET", `/api/patients/${id}`); S.tab = tab; go("chart"); }
async function reloadChart() { S.chart = await api("GET", `/api/patients/${S.chart.patient.id}`); go("chart"); }

function patientBanner(c) {
  const p = c.patient;
  const allergies = (c.allergies || []).map((a) => a.substance);
  return h("div", { class: "banner", role: "region", "aria-label": "Patient" },
    h("span", { class: "name" }, `${p.last_name.toUpperCase()}, ${p.first_name}`),
    h("span", { class: "id" }, `DOB ${fmtDate(p.dob)} (${p.age}y) · ${p.sex}`),
    h("span", { class: "id" }, "IHI ", p.ihi_display || "—"),
    p.gms_number ? h("span", { class: "id" }, `${p.eligibility.toUpperCase()} ${p.gms_number}`) : h("span", { class: "id" }, p.eligibility.toUpperCase()),
    h("span", { class: "id" }, `Chart ${p.id}`),
    allergies.length ? h("span", { class: "flag" }, "Allergies: " + allergies.join(", ")) : h("span", { class: "id" }, "No allergies recorded"),
    p.processing_restricted ? h("span", { class: "flag" }, "Processing restricted (GDPR)") : null,
    p.record_status !== "active" ? h("span", { class: "flag" }, p.record_status) : null,
    p.deceased_date ? h("span", { class: "flag" }, "Deceased " + fmtDate(p.deceased_date)) : null);
}

async function viewChart() {
  const c = S.chart;
  const tabs = [["summary", "Summary"], ["consult", "Consultations"], ["prescribe", "Medication"], ["results", "Results & letters"],
    ["imms", "Immunisations"], ["cdm", "Chronic disease"], ["comms", "Referrals & Healthmail"], ["details", "Details"]]
    .filter(([k]) => can("clinical.read") || ["summary", "details"].includes(k));
  const body = await ({ summary: tabSummary, consult: tabConsult, prescribe: tabPrescribe, results: tabResults, imms: tabImms, cdm: tabCdm, comms: tabComms, details: tabDetails })[S.tab](c);
  return h("div", {}, patientBanner(c),
    h("div", { class: "tabs", role: "tablist" }, tabs.map(([k, l]) => h("button", { role: "tab", class: S.tab === k ? "active" : "", onclick: () => { S.tab = k; go("chart"); } }, l))),
    body);
}

function cdmPill(cdm) {
  if (!cdm || !cdm.status) return null;
  const map = { green: ["ok", "CDM up to date"], orange: ["warn", "CDM review started"], red: ["bad", "CDM review due"] };
  const [cls, label] = map[cdm.status];
  return h("span", { class: "pill " + cls }, label);
}

function tabSummary(c) {
  const p = c.patient;
  const activeProblems = (c.problems || []).filter((x) => x.status === "active");
  const repeats = (c.prescriptions || []).flatMap((r) => r.items.filter((i) => i.is_repeat_medication && r.status !== "cancelled").map((i) => ({ ...i, rx: r })));
  const lastObs = {};
  (c.observations || []).forEach((o) => { if (!lastObs[o.kind]) lastObs[o.kind] = o; });
  const missing = p.missing_desirable || [];
  return h("div", { class: "grid2" },
    card("Problems", cdmPill(c.cdm), can("clinical.read") ? table([["Code", (x) => x.icpc2_code || ""], ["Problem", (x) => x.description], ["Since", (x) => fmtDate(x.onset || x.recorded_at)]], activeProblems) : h("p", { class: "muted" }, "Clinical details hidden for your role"),
      can("clinical.write") ? addProblem() : null),
    card("Allergies & intolerances", null, table([["Substance", (a) => a.substance], ["Reaction", (a) => a.reaction || ""], ["Severity", (a) => a.severity]], c.allergies || []), can("clinical.write") ? addAllergy() : null),
    can("clinical.read") ? card("Repeat medication", null, table([["Drug", (i) => [i.drug_name, i.strength].filter(Boolean).join(" ")], ["Dose", (i) => i.dose_instructions], ["Last issued", (i) => fmtDate(i.rx.created_at)]], repeats)) : null,
    can("clinical.read") ? card("Latest measurements", null, table([["Measure", (o) => (OBS_KINDS.find((k) => k[0] === o.kind) || [0, o.kind])[1]], ["Value", (o) => `${o.value} ${o.unit || ""}`], ["Date", (o) => fmtDate(o.taken_at)]], Object.values(lastObs)), can("clinical.write") ? addObservation() : null) : null,
    can("clinical.read") ? card("Recent consultations", null, (c.consultations || []).slice(0, 3).map(noteView)) : null,
    card("Contact", null, h("p", {}, [p.address1, p.address2, p.town, p.county, p.eircode].filter(Boolean).join(", ")),
      h("p", {}, "Mobile ", p.phone_mobile || "—", " · Email ", p.email || "—"),
      h("p", { class: "small" }, "Consents: ", ["sms", "email", "video"].filter((k) => p["consent_" + k]).join(", ") || "none recorded"),
      missing.length ? h("div", { class: "alert warn small" }, "Missing: " + missing.join(", ")) : null));
}
function addProblem() {
  const f = form([["icpc2_code", "ICPC-2 code"], ["description", "Description (optional if coded)"], ["onset", "Onset", "date"]]);
  attachIcpcLookup(f.querySelector("[name=icpc2_code]"));
  return h("details", {}, h("summary", {}, "Add problem"), f, btn("Add", async () => { await api("POST", `/api/patients/${S.chart.patient.id}/problems`, readForm(f)); reloadChart(); }));
}
function addAllergy() {
  const f = form([["substance", "Substance"], ["reaction", "Reaction"], ["severity", "Severity", "select", ["unknown", "mild", "moderate", "severe"]]]);
  return h("details", {}, h("summary", {}, "Add allergy"), f, btn("Add", async () => { await api("POST", `/api/patients/${S.chart.patient.id}/allergies`, readForm(f)); reloadChart(); }));
}
const OBS_KINDS = [["bp_systolic", "BP systolic", "mmHg"], ["bp_diastolic", "BP diastolic", "mmHg"], ["pulse_rate", "Pulse", "bpm"], ["weight_kg", "Weight", "kg"], ["height_cm", "Height", "cm"], ["waist_cm", "Waist", "cm"], ["peak_flow", "Peak flow", "L/min"], ["hba1c", "HbA1c", "mmol/mol"], ["total_cholesterol", "Cholesterol", "mmol/L"], ["egfr", "eGFR", "mL/min"], ["temperature", "Temperature", "°C"], ["spo2", "SpO2", "%"]];
function addObservation() {
  const f = form([["kind", "Measure", "select", OBS_KINDS.map(([k, l]) => [k, l])], ["value", "Value", "number"]]);
  return h("details", {}, h("summary", {}, "Record measurement"), f, btn("Save", async () => {
    const d = readForm(f); d.unit = (OBS_KINDS.find((k) => k[0] === d.kind) || [])[2];
    await api("POST", `/api/patients/${S.chart.patient.id}/observations`, d); reloadChart();
  }));
}
function attachIcpcLookup(input) {
  const list = h("datalist", { id: "icpc-" + Math.random().toString(36).slice(2) });
  input.setAttribute("list", list.id);
  input.after(list);
  input.addEventListener("input", async () => {
    const rows = await api("GET", "/api/icpc2?q=" + encodeURIComponent(input.value));
    list.replaceChildren(...rows.map((r) => h("option", { value: r.code }, `${r.code} ${r.title}`)));
  });
}

function noteView(n) {
  const fields = [["S", n.subjective], ["O", n.objective], ["A", n.assessment], ["P", n.plan]].filter(([, v]) => v);
  const editable = !n.signed_at && n.clinician_id === S.me.user.id && Date.now() - new Date(n.started_at) < 12 * 3600e3;
  return h("div", { class: "note" + (n.entered_in_error ? " err" : "") },
    h("div", { class: "meta" }, `${fmtDT(n.started_at)} · ${n.clinician_name} · ${n.mode}`, n.icpc2_code ? ` · ${n.icpc2_code}` : "",
      n.signed_at ? " · signed" : editable ? " · editable until locked" : "", n.entered_in_error ? ` · ENTERED IN ERROR: ${n.error_reason}` : "",
      n.mode !== "surgery" && n.mode !== "home" ? ` · consent ${n.remote_consent_recorded ? "✓" : "✗"} · ID ${n.remote_identity_verified ? "✓" : "✗"}` : ""),
    fields.map(([k, v]) => h("p", {}, h("strong", {}, k + ": "), v)),
    (n.addenda || []).map((a) => h("div", { class: "addendum" }, h("span", { class: "meta" }, `Addendum ${fmtDT(a.created_at)} · ${userName(a.user_id)}: `), a.text)),
    can("clinical.write") && !n.entered_in_error ? h("div", { class: "row small" },
      editable ? h("a", { href: "#", onclick: (e) => { e.preventDefault(); editNote(n); } }, "Edit") : null,
      h("a", { href: "#", onclick: async (e) => { e.preventDefault(); const t = prompt("Addendum"); if (t) { await api("POST", `/api/consultations/${n.id}/addenda`, { text: t }); reloadChart(); } } }, "Add addendum"),
      h("a", { href: "#", onclick: async (e) => { e.preventDefault(); const r = prompt("Reason this note was entered in error"); if (r) { await api("POST", `/api/consultations/${n.id}/entered-in-error`, { reason: r }); reloadChart(); } } }, "Entered in error")) : null);
}

function consultForm(n = {}) {
  const f = form([["mode", "Type", "select", [["surgery", "In surgery"], ["phone", "Phone"], ["video", "Video"], ["home", "Home visit"], ["nursing_home", "Nursing home"]]],
    ["icpc2_code", "ICPC-2 reason code"], ["add_problem", "Add code to problem list", "checkbox"],
    ["subjective", "History (S)", "textarea"], ["objective", "Examination (O)", "textarea"], ["assessment", "Assessment (A)", "textarea"], ["plan", "Plan (P)", "textarea"],
    ["remote_consent_recorded", "Remote: patient consented to phone/video consultation", "checkbox"], ["remote_identity_verified", "Remote: identity confirmed (name, DOB, address)", "checkbox"]], n);
  attachIcpcLookup(f.querySelector("[name=icpc2_code]"));
  return f;
}
function editNote(n) {
  const f = consultForm(n);
  const main = document.getElementById("main");
  main.prepend(card("Edit consultation", null, f, h("div", { class: "row" },
    btn("Save", async () => { await api("PATCH", `/api/consultations/${n.id}`, readForm(f)); reloadChart(); }),
    btn("Save & sign", async () => { await api("PATCH", `/api/consultations/${n.id}`, { ...readForm(f), sign: true }); reloadChart(); }, "secondary"))));
}

function tabConsult(c) {
  const open = (c.consultations || []).find((n) => !n.signed_at && n.clinician_id === S.me.user.id && !n.subjective && !n.plan);
  const f = consultForm(open ? { mode: open.mode } : {});
  const save = async (sign) => {
    const d = readForm(f);
    if (open) await api("PATCH", `/api/consultations/${open.id}`, { ...d, sign });
    else await api("POST", `/api/patients/${c.patient.id}/consultations`, { ...d, sign });
    toast(sign ? "Consultation signed" : "Saved"); reloadChart();
  };
  setTimeout(() => f.querySelector("[name=subjective]")?.focus(), 0);
  return h("div", {},
    can("clinical.write") ? card(open ? "Continue consultation" : "New consultation", null, f, h("div", { class: "row" }, btn("Save", () => save(false)), btn("Save & sign", () => save(true), "secondary"),
      h("span", { class: "small muted" }, "Notes can be edited by the author for 12 hours unless signed; after that, add an addendum."))) : null,
    card("History", null, (c.consultations || []).map(noteView)));
}

function rxItemRow() {
  return form([["drug_name", "Drug"], ["strength", "Strength"], ["form", "Form"], ["dose_instructions", "Dose"], ["quantity", "Quantity"], ["repeats", "Repeats", "number"],
    ["is_repeat_medication", "Repeat medication", "checkbox"], ["cd_schedule", "Controlled drug", "select", [["", "No"], "CD1", "CD2", "CD3", "CD4", "CD5"]], ["is_ost", "Opiate substitution (OST)", "checkbox"], ["generic_substitution_allowed", "Generic substitution allowed", "checkbox"]],
  { generic_substitution_allowed: true, repeats: 0 });
}
function tabPrescribe(c) {
  const items = h("div", {}, rxItemRow());
  const warn = h("div", {});
  const prescriberSel = h("select", {}, S.users.filter((u) => ["gp", "nurse_prescriber"].includes(u.role) && u.active).map((u) => h("option", { value: u.id, selected: u.id === S.me.user.id }, u.full_name)));
  const create = async (ack) => {
    const its = [...items.children].map(readForm).filter((i) => i.drug_name);
    its.forEach((i) => { i.repeats = Number(i.repeats || 0); });
    const r = await api("POST", `/api/patients/${c.patient.id}/prescriptions`, { items: its, acknowledge_warnings: ack, prescriber_id: Number(prescriberSel.value) });
    if (!r.saved) {
      warn.replaceChildren(h("div", { class: "alert bad" }, r.warnings.map((w) => h("div", {}, w)), btn("Prescribe anyway", () => create(true), "danger")));
      return;
    }
    toast("Prescription saved"); reloadChart();
  };
  const represcribe = (rx) => {
    items.replaceChildren(...rx.items.map((i) => { const row = rxItemRow(); for (const [k, v] of Object.entries(i)) { const el = row.querySelector(`[name=${k}]`); if (el) el.type === "checkbox" ? (el.checked = !!v) : (el.value = v ?? ""); } return row; }));
    toast("Copied — review and save");
  };
  return h("div", {},
    can("clinical.write") ? card("New prescription", h("span", { class: "row small" }, "Prescriber", prescriberSel), items,
      h("div", { class: "row" }, btn("+ item", () => items.append(rxItemRow()), "secondary"), btn("Save prescription", () => create(false))), warn,
      h("p", { class: "small muted" }, "Any clinician can draft; only a GP or nurse prescriber can issue or send. Drug–drug interaction checking requires the licensed drug database to be connected.")) : null,
    card("Prescriptions", null, table([
      ["Date", (r) => fmtDate(r.created_at)], ["Items", (r) => r.items.map((i) => `${i.drug_name} ${i.strength || ""} — ${i.dose_instructions} ×${i.quantity}`).join("; ")],
      ["By", (r) => r.prescriber_name], ["Status", (r) => h("span", { class: "pill" + (r.status === "sent" ? " ok" : r.status === "cancelled" ? " bad" : "") }, r.status + (r.sent_via ? " · " + r.sent_via : ""))],
      ["", (r) => h("span", { class: "row" }, r.status !== "cancelled" ? [
        h("a", { href: `/api/prescriptions/${r.id}/pdf`, target: "_blank" }, "Print"),
        can("prescription.send") && ["draft", "issued"].includes(r.status) ? btn("Send to pharmacy", async () => {
          const to = prompt("Pharmacy Healthmail address", r.pharmacy_healthmail || c.patient.preferred_pharmacy_healthmail || "");
          if (!to) return;
          const hasCd = r.items.some((i) => ["CD2", "CD3"].includes(i.cd_schedule));
          if (hasCd && !confirm("Contains a Schedule 2/3 controlled drug. Confirm electronic transfer is permitted under current rules.")) return;
          await api("POST", `/api/prescriptions/${r.id}/send-healthmail`, { pharmacy_healthmail: to, confirm_cd: hasCd }); toast("Sent via Healthmail"); reloadChart();
        }) : null,
        can("clinical.write") ? btn("Re-prescribe", () => represcribe(r), "secondary") : null,
        can("prescribe") && r.status !== "sent" ? h("a", { href: "#", onclick: async (e) => { e.preventDefault(); if (confirm("Cancel this prescription?")) { await api("POST", `/api/prescriptions/${r.id}/cancel`, { reason: "cancelled" }); reloadChart(); } } }, "Cancel") : null] : null)],
    ], c.prescriptions || [])));
}

function resultsTable(results) {
  return table([["Test", (r) => r.test_name], ["Value", (r) => `${r.value || ""} ${r.units || ""}`], ["Range", (r) => r.reference_range || ""],
    ["Flag", (r) => (r.abnormal_flag && r.abnormal_flag !== "N" ? h("span", { class: "pill bad" }, r.abnormal_flag) : "")], ["Date", (r) => fmtDate(r.observed_at)]], results);
}
function tabResults(c) {
  return h("div", {}, (c.results || []).map((m) => card(`${fmtDT(m.received_at)} · ${(m.summary || "").split("\n")[0]}`,
    h("span", { class: "pill" + (m.status === "filed" ? " ok" : " warn") }, m.status + (m.action ? " · " + m.action.replace("_", " ") : "")),
    m.results.length ? resultsTable(m.results) : null, h("pre", { class: "msg" }, (m.summary || "").split("\n").slice(1).join("\n").trim() || ""),
    m.review_comment ? h("p", { class: "small" }, "Comment: ", m.review_comment) : null)),
  (c.results || []).length ? null : h("p", { class: "muted" }, "No results or letters."));
}

function tabImms(c) {
  const f = form([["vaccine", "Vaccine"], ["batch", "Batch"], ["expiry", "Vial expiry", "date"], ["use_by", "Use-by (mRNA after thaw)", "date"], ["dose_number", "Dose no.", "number"],
    ["dose_kind", "Dose type", "select", ["primary", "booster"]], ["dose_volume_ml", "Volume (ml)", "number"], ["site", "Site", "select", ["", "L deltoid", "R deltoid", "L thigh", "R thigh"]],
    ["route", "Route", "select", ["IM", "SC", "intranasal", "oral"]], ["consent", "Consent", "select", [["given", "Given"], ["refused", "Refused"]]], ["contraindications", "Contraindications noted", "textarea"]]);
  return h("div", {},
    can("immunise") ? card("Record vaccination", null, f, btn("Save", async () => { const d = readForm(f); ["dose_number", "dose_volume_ml"].forEach((k) => d[k] && (d[k] = Number(d[k]))); await api("POST", `/api/patients/${c.patient.id}/immunisations`, d); toast("Recorded"); reloadChart(); })) : null,
    card("Vaccinations", null, table([["Date", (i) => fmtDate(i.given_at)], ["Vaccine", (i) => i.vaccine], ["Dose", (i) => [i.dose_number, i.dose_kind].filter(Boolean).join(" ")], ["Batch", (i) => i.batch || ""], ["Consent", (i) => i.consent]], c.immunisations || [])));
}

async function tabCdm(c) {
  const pre = await api("GET", `/api/patients/${c.patient.id}/cdm/prefill`);
  if (!pre.registers.length) return card("Chronic Disease Management", null, h("p", { class: "muted" }, "Not on a CDM register. Code a qualifying problem (T90, R96, R95, K77, K74–K76, K89/K90, K78) to start."));
  const last = c.cdm?.last_review;
  const data = last && last.status === "started" ? { ...pre.data, ...JSON.parse(last.data || "{}") } : pre.data;
  const f = form(pre.required.map((k) => [k, k.replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase())]), data);
  const plan = h("textarea", { value: (last && last.status === "started" && last.care_plan) || "" });
  const missingBox = h("div", {});
  const save = async (complete) => {
    const r = await api("POST", `/api/patients/${c.patient.id}/cdm`, { id: last && last.status === "started" ? last.id : null, conditions: pre.registers, data: readForm(f), care_plan: plan.value, complete });
    toast(complete ? "Review complete — return queued" : "Saved (review in progress)");
    if (r.missing.length) missingBox.replaceChildren(h("div", { class: "alert warn" }, "Still needed: " + r.missing.join(", ")));
    reloadChart();
  };
  return h("div", {}, card("CDM review: " + pre.register_titles.join(", "), cdmPill(c.cdm),
    !pre.eligible ? h("div", { class: "alert warn" }, "Patient is not GMS/GPVC: the review is recorded but not claimable.") : null,
    h("p", { class: "small muted" }, "Values recorded in the last 6 months are filled in automatically. The return can only be sent once every field is complete."),
    pre.missing.length ? h("div", { class: "alert warn small" }, "Missing: " + pre.missing.join(", ")) : null,
    f, h("label", {}, "Agreed care plan", plan), missingBox,
    h("div", { class: "row" }, btn("Save progress", () => save(false), "secondary"), btn("Complete review", () => save(true)),
      last && last.status === "complete" ? h("a", { href: `/api/patients/${c.patient.id}/cdm/${last.id}/care-plan`, target: "_blank" }, "Print last care plan") : null)));
}

async function tabComms(c) {
  const log = await api("GET", `/api/patients/${c.patient.id}/outbound`);
  const ref = form([["receiving_facility", "Hospital (Healthlink code)"], ["specialty", "Specialty"], ["priority", "Priority", "select", [["R", "Routine"], ["U", "Urgent"]]], ["reason", "Reason for referral", "textarea"], ["history", "History", "textarea"], ["medications", "Current medication", "textarea"]]);
  const hm = form([["to", "To (Healthmail addresses, comma-separated)"], ["subject", "Subject"], ["body", "Message", "textarea"]]);
  const file = h("input", { type: "file", multiple: true });
  const cert = form([["illness_text", "Illness"], ["illness_code", "ICPC-2 code"], ["date_from", "From", "date"], ["weeks", "Weeks", "number"], ["cert_type", "Type", "select", ["first", "intermediate", "final"]]]);
  return h("div", { class: "grid2" },
    can("referral.send") ? card("eReferral via Healthlink", null, ref, btn("Send referral", async () => { await api("POST", `/api/patients/${c.patient.id}/referrals`, readForm(ref)); toast("Referral queued for Healthlink"); go("chart"); })) : null,
    can("healthmail.send") ? card("Secure Healthmail", null, hm, h("label", {}, "Attachments (letters, photos, ECGs)", file), btn("Send", async () => {
      const atts = await Promise.all([...file.files].map((f) => new Promise((res) => { const r = new FileReader(); r.onload = () => res({ filename: f.name, mime: f.type || "application/octet-stream", content_b64: r.result.split(",")[1] }); r.readAsDataURL(f); })));
      await api("POST", `/api/patients/${c.patient.id}/healthmail`, { ...readForm(hm), attachments: atts }); toast("Sent via Healthmail"); go("chart");
    })) : null,
    can("sickcert.write") ? card("Medical certificate (DSP)", null, cert, btn("Create certificate", async () => { const d = readForm(cert); d.weeks = Number(d.weeks); const r = await api("POST", `/api/patients/${c.patient.id}/sick-certs`, d); window.open(`/api/sick-certs/${r.id}/pdf`, "_blank"); reloadChart(); })) : null,
    card("Sent", null, table([["Date", (o) => fmtDT(o.created_at)], ["Via", (o) => o.channel], ["What", (o) => o.kind], ["To", (o) => o.recipient], ["Status", (o) => h("span", { class: "pill" + (o.status === "failed" || o.status === "rejected" ? " bad" : " ok") }, o.status)]], log)));
}

function tabDetails(c) {
  const f = patientForm(c.patient);
  return h("div", {}, card("Demographics", null, f, can("patient.write") ? btn("Save changes", async () => {
    const d = cleanPatient(readForm(f));
    if (!can("patient.ppsn")) { delete d.ppsn; delete d.ihi; }
    else if (d.ppsn && d.ppsn.startsWith("•")) delete d.ppsn;
    await api("PATCH", `/api/patients/${c.patient.id}`, d); toast("Saved"); reloadChart();
  }) : null),
  can("patient.write") ? card("Leaving the practice", null, (() => {
    const g = form([["reason", "Reason"], ["date", "Date", "date"], ["deceased_date", "Date of death (if deceased)", "date"], ["cause_of_death", "Cause of death"]]);
    return h("div", {}, g, btn("Deregister", async () => { if (confirm("Mark this patient as having left the practice?")) { await api("POST", `/api/patients/${c.patient.id}/deregister`, readForm(g)); reloadChart(); } }, "danger"));
  })()) : null);
}

// --------------------------------------------------------------- inbox
async function viewInbox(filter = {}) {
  const status = filter.status || "new";
  const rows = await api("GET", `/api/inbox?status=${status}${filter.unmatched ? "&unmatched=true" : ""}${filter.mine ? "&provider=" + S.me.user.id : ""}`);
  const detail = h("div", {});
  const show = async (m) => {
    const full = await api("GET", `/api/inbox/${m.id}`);
    const actions = h("div", { class: "row" });
    if (!full.patient_id) {
      const q = h("input", { placeholder: "Search patient to match" });
      const res = h("div", {});
      q.addEventListener("input", async () => { const ps = await api("GET", "/api/patients?q=" + encodeURIComponent(q.value)); res.replaceChildren(table([["Patient", (p) => `${p.last_name}, ${p.first_name} ${fmtDate(p.dob)}`]], ps, async (p) => { await api("POST", `/api/inbox/${m.id}/match`, { patient_id: p.id }); show(m); })); });
      actions.append(h("div", { class: "alert warn" }, "Not matched. Message says: ", full.match_hint), q, res);
    } else if (can("inbox.review") && full.status !== "filed") {
      const comment = h("input", { placeholder: "Comment / instruction for reception", size: 40 });
      const assign = h("select", {}, h("option", { value: "" }, "Assign task to…"), S.users.filter((u) => u.active).map((u) => h("option", { value: u.id }, u.full_name)));
      actions.append(comment, assign, ...[["normal", "Normal — file"], ["no_action", "No action"], ["contact_patient", "Contact patient"], ["book_appointment", "Book appointment"], ["repeat_test", "Repeat test"]].map(([k, l]) =>
        btn(l, async () => { await api("POST", `/api/inbox/${m.id}/review`, { action: k, comment: comment.value, assign_to: assign.value ? Number(assign.value) : null }); toast("Filed"); go("inbox"); }, k === "normal" ? "" : "secondary")));
    }
    detail.replaceChildren(card((full.summary || "").split("\n")[0], full.patient_label ? btn("Open chart", () => openChart(full.patient_id), "secondary") : null,
      h("p", { class: "small muted" }, `Received ${fmtDT(full.received_at)} from ${full.sender || "?"} · ${full.message_type}`, full.patient_label ? " · " + full.patient_label : ""),
      full.results.length ? resultsTable(full.results) : null, h("pre", { class: "msg" }, (full.summary || "").split("\n").slice(1).join("\n").trim()), actions));
  };
  const upload = h("input", { type: "file", accept: ".hl7,.xml,.txt" });
  return h("div", {}, h("h2", {}, "Inbox"),
    h("div", { class: "row" }, btn("New", () => viewInbox({}).then(layout), status === "new" && !filter.unmatched ? "" : "secondary"),
      btn("Assigned to me", () => viewInbox({ mine: true }).then(layout), filter.mine ? "" : "secondary"),
      btn("Unmatched", () => viewInbox({ unmatched: true }).then(layout), filter.unmatched ? "" : "secondary"),
      btn("Filed", () => viewInbox({ status: "filed" }).then(layout), status === "filed" ? "" : "secondary"),
      btn("Check Healthlink now", async () => { const r = await api("POST", "/api/inbox/poll"); toast(r.enabled ? `Received ${r.received}, failed ${r.failed}` : "Healthlink disabled"); go("inbox"); }, "secondary"),
      upload, btn("Import file", async () => { if (!upload.files[0]) return; const fd = new FormData(); fd.append("file", upload.files[0]); await api("POST", "/api/inbox/upload", fd); go("inbox"); }, "secondary")),
    card("Messages", null, table([["Received", (m) => fmtDT(m.received_at)], ["Patient", (m) => m.patient_label || h("span", { class: "pill warn" }, "unmatched")], ["Message", (m) => m.title],
      ["", (m) => (m.abnormal ? h("span", { class: "pill bad" }, "abnormal") : "")], ["For", (m) => userName(m.assigned_to)]], rows, show)), detail);
}

// --------------------------------------------------------------- tasks
async function viewTasks() {
  const mine = await api("GET", "/api/tasks?mine=true");
  const all = await api("GET", "/api/tasks?mine=false");
  const f = form([["title", "Task"], ["due", "Due", "date"], ["assigned_to", "Assign to", "select", [["", "Me"], ...S.users.filter((u) => u.active).map((u) => [u.id, u.full_name])]]]);
  const done = (t) => btn("Done", async (e) => { e.stopPropagation(); await api("POST", `/api/tasks/${t.id}/done`); go("tasks"); }, "secondary");
  const cols = [["Due", (t) => fmtDate(t.due)], ["Task", (t) => t.title], ["For", (t) => userName(t.assigned_to)], ["", done]];
  return h("div", {}, h("h2", {}, "Tasks"), card("My tasks", null, table(cols, mine, (t) => t.patient_id && openChart(t.patient_id))),
    card("All open tasks", null, table(cols, all, (t) => t.patient_id && openChart(t.patient_id))),
    card("New task", null, f, btn("Add", async () => { const d = readForm(f); d.assigned_to = d.assigned_to ? Number(d.assigned_to) : null; await api("POST", "/api/tasks", d); go("tasks"); })));
}

// --------------------------------------------------------------- reports
async function viewReports() {
  const [cdm, cerv, inc, act] = await Promise.all(["/api/reports/cdm-due", "/api/reports/cervical-screening", "/api/reports/incomplete", "/api/reports/activity"].map((u) => api("GET", u)));
  const open = (r) => openChart(r.id);
  return h("div", {}, h("h2", {}, "Reports"),
    card("Chronic disease reviews due", can("claims.write") ? h("a", { href: "/api/claims/export.csv" }, "Export pending claims (CSV)") : null,
      table([["Patient", (r) => r.name], ["Registers", (r) => r.registers.join(", ")], ["Type", (r) => r.eligibility], ["Status", (r) => cdmPill({ status: r.status })]], cdm, open)),
    card("Cervical screening: no result on file (women 25–65)", null, table([["Patient", (r) => r.name], ["Age", (r) => r.age], ["Mobile", (r) => r.phone_mobile || ""]], cerv, open)),
    card("Incomplete records", null, table([["Patient", (r) => r.name], ["Missing", (r) => r.missing.join(", ")]], inc, open)),
    card("Consultations this month", null, table([["Clinician", (r) => r.clinician], ["Type", (r) => r.mode], ["Count", (r) => r.count]], act)));
}

// --------------------------------------------------------------- governance
async function viewGovernance() {
  const [dsr, breaches, retention, verify] = await Promise.all(["/api/dsr", "/api/breaches", "/api/reports/retention", "/api/audit/verify"].map((u) => api("GET", u).catch(() => null)));
  const dsrForm = form([["patient_id", "Chart no."], ["request_type", "Request", "select", ["access", "rectification", "restriction", "objection", "portability", "erasure"]], ["received_at", "Received", "date"], ["identity_verified", "Identity verified", "checkbox"]]);
  const bForm = form([["description", "What happened", "textarea"], ["detected_at", "Detected", "datetime-local"], ["patients_affected", "Patients affected", "number"], ["risk", "Risk", "select", ["unassessed", "none", "low", "risk", "high"]], ["actions", "Containment actions", "textarea"]]);
  const auditBox = h("div", {});
  const auditQ = h("input", { placeholder: "Chart no.", size: 8 });
  return h("div", {}, h("h2", {}, "Data protection"),
    verify ? h("div", { class: "alert " + (verify.ok ? "" : "bad") }, verify.ok ? `Audit trail intact (${verify.checked} entries verified).` : `AUDIT TRAIL BROKEN at entry ${verify.broken_at_id}. Investigate and report.`) : null,
    card("Data subject requests (respond within one month)", null, dsr ? table([["Received", (r) => fmtDate(r.received_at)], ["Chart", (r) => r.patient_id || ""], ["Type", (r) => r.request_type], ["Due", (r) => h("span", { class: "pill" + (r.overdue ? " bad" : "") }, fmtDate(r.due_at))], ["Status", (r) => r.status],
      ["", (r) => h("span", { class: "row" }, r.patient_id && ["access", "portability"].includes(r.request_type) ? h("a", { href: `/api/patients/${r.patient_id}/export?purpose=${r.request_type}` }, "Export record") : null,
        r.status !== "completed" ? btn("Close", async () => { await api("POST", `/api/dsr/${r.id}/close`, { status: "completed", outcome: prompt("Outcome") }); go("governance"); }, "secondary") : null)]], dsr) : null,
    h("details", {}, h("summary", {}, "Log a request"), dsrForm, btn("Save", async () => { const d = readForm(dsrForm); d.patient_id = d.patient_id ? Number(d.patient_id) : null; await api("POST", "/api/dsr", d); go("governance"); }))),
    card("Personal data breaches (notify the DPC within 72 hours unless unlikely to cause risk)", null, breaches ? table([["Detected", (b) => fmtDT(b.detected_at)], ["What", (b) => b.description], ["Risk", (b) => b.risk],
      ["DPC", (b) => (b.dpc_notified_at ? "notified " + fmtDT(b.dpc_notified_at) : h("span", { class: "pill" + (b.dpc_overdue ? " bad" : " warn") }, "deadline " + fmtDT(b.dpc_deadline)))],
      ["", (b) => (!b.dpc_notified_at ? btn("Mark DPC notified", async () => { await api("PATCH", `/api/breaches/${b.id}`, { dpc_notified_at: new Date().toISOString() }); go("governance"); }, "secondary") : null)]], breaches) : null,
    h("details", {}, h("summary", {}, "Record a breach"), bForm, btn("Save", async () => { const d = readForm(bForm); if (d.detected_at) d.detected_at = new Date(d.detected_at).toISOString(); d.patients_affected = d.patients_affected ? Number(d.patients_affected) : null; await api("POST", "/api/breaches", d); go("governance"); }))),
    card("Records due for retention review", null, h("p", { class: "small muted" }, "Inactive records past the minimum retention period. Nothing is deleted automatically: review each one and archive only if there is no reason to keep it longer."),
      retention ? table([["Patient", (r) => r.name], ["DOB", (r) => fmtDate(r.dob)], ["Retain until", (r) => fmtDate(r.retain_until)], ["", (r) => btn("Archive", async () => { await api("POST", `/api/patients/${r.id}/archive`, { note: prompt("Review note") }); go("governance"); }, "secondary")]], retention) : null),
    can("audit.read") ? card("Audit log", h("span", { class: "row" }, auditQ, btn("Show", async () => {
      const rows = await api("GET", "/api/audit?limit=300" + (auditQ.value ? "&patient_id=" + Number(auditQ.value) : ""));
      auditBox.replaceChildren(table([["When", (e) => fmtDT(e.at)], ["User", (e) => e.username || "system"], ["Action", (e) => e.action], ["Chart", (e) => e.patient_id || ""], ["Detail", (e) => (e.detail || "").slice(0, 120)]], rows));
    }, "secondary")), auditBox) : null);
}

// --------------------------------------------------------------- settings
async function viewSettings() {
  const hmf = form([["address", "Your Healthmail address"], ["password", "Healthmail password", "password"]], { address: S.me.user.healthmail_address || "" });
  const blocks = [h("h2", {}, "My settings"),
    card("Healthmail", null, h("p", { class: "small muted" }, "Link your own Healthmail account. Messages and prescriptions you send are sent from it, and only while you are signed in."), hmf,
      btn("Link account", async () => { await api("POST", "/api/auth/healthmail-account", readForm(hmf)); toast("Healthmail linked"); }))];
  if (can("users.manage")) {
    const uf = form([["username", "Username"], ["full_name", "Full name"], ["role", "Role", "select", ["gp", "nurse", "nurse_prescriber", "reception", "practice_manager", "sysadmin"]], ["password", "Temporary password (12+)", "password"], ["mcrn", "IMC number"], ["nmbi_pin", "NMBI PIN"], ["gms_doctor_number", "GMS doctor no."], ["healthmail_address", "Healthmail"]]);
    blocks.push(card("Staff accounts", null, table([["Name", (u) => u.full_name], ["Username", (u) => u.username], ["Role", (u) => u.role], ["2FA", (u) => (u.mfa_enabled ? "on" : "not set up")], ["Active", (u) => (u.active ? "yes" : "no")],
      ["", (u) => (u.active && u.id !== S.me.user.id ? btn("Deactivate", async () => { if (confirm(`Deactivate ${u.full_name}?`)) { await api("POST", `/api/auth/users/${u.id}/deactivate`); S.users = await api("GET", "/api/auth/users"); go("settings"); } }, "danger") : null)]], S.users),
      h("details", {}, h("summary", {}, "Add staff member"), uf, btn("Create", async () => { await api("POST", "/api/auth/users", readForm(uf)); S.users = await api("GET", "/api/auth/users"); go("settings"); }))));
  }
  return h("div", {}, blocks);
}

// --------------------------------------------------------------- boot
(async function boot() {
  try {
    const me = await api("GET", "/api/auth/session", undefined, { allow401: true, raw: true });
    if (me.ok) { const d = await me.json(); S.csrf = d.csrf; if (d.mfa_passed) return start(d); return renderMfa(d); }
  } catch (e) {}
  renderLogin();
})();
