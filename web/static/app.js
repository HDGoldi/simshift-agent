// SIMShift decision-trace UI. Vanilla JS; all values come from the API, nothing is invented here.
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;

let current = null; // snapshot of the live incident
let busy = false;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || r.statusText);
  return r.json();
}

// ------------------------------------------------------------------ header
async function loadHealth() {
  const chip = $("decider-chip");
  try {
    const h = await api("/api/health");
    if (h.decider === "up") {
      chip.textContent = h.fake ? "FAKE DECIDER (UI test mode)" : `Decider: ${h.model} · ${h.device}`;
      chip.className = "chip " + (h.fake ? "bad" : "ok");
    } else {
      chip.textContent = "Decider: offline";
      chip.className = "chip bad";
    }
  } catch { chip.textContent = "Decider: unknown"; chip.className = "chip bad"; }
}

// ------------------------------------------------------------------ scenarios
async function loadScenarios() {
  const list = await api("/api/scenarios");
  $("scenarios").innerHTML = list.map((s) => `
    <div role="listitem"><button class="scn" aria-pressed="false" data-name="${esc(s.name)}">
      <b>${esc(s.id)}</b><span>${esc(s.incident)} · ${s.affected_devices.toLocaleString()} devices</span>
    </button></div>`).join("");
  document.querySelectorAll(".scn").forEach((b) => b.addEventListener("click", () => start(b.dataset.name)));
}

async function start(name) {
  if (busy) return;
  document.querySelectorAll(".scn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.name === name)));
  $("cf-out").innerHTML = "";
  render(await api("/api/incidents", { scenario: name }));
}

// ------------------------------------------------------------------ actions
async function step() {
  if (!current || busy) return;
  setBusy(true);
  try { render(await api(`/api/incidents/${current.id}/step`, {})); }
  catch (e) { alert(`Step failed: ${e.message}`); }
  finally { setBusy(false); }
}

async function runToEnd() {
  while (current && !current.done && !current.awaiting_approval) {
    await step();
    if (!current) break;
  }
}

async function decide(approved) {
  setBusy(true);
  try { render(await api(`/api/incidents/${current.id}/approval`, { approved })); }
  finally { setBusy(false); }
}

async function counterfactual(kind) {
  if (!current) return;
  const out = $("cf-out");
  out.textContent = "Running on a clone…";
  try {
    let res, label;
    if (kind === "force") {
      res = await api("/api/force-profile-change", { scenario: current.scenario });
      label = "Forced profile change (operator override)";
    } else {
      const actions = kind.split(",");
      res = await api("/api/counterfactual", { scenario: current.scenario, actions, approve: true });
      label = `What if: ${actions.join(" → ")}`;
    }
    const o = res.outcome;
    const blocked = res.result && res.result.executed === false
      ? `<div style="color:var(--bad)"><b>BLOCKED:</b> ${esc(res.result.blocked_reasons.join("; "))}</div>` : "";
    out.innerHTML = `<div class="cf-card"><div class="label">Counterfactual · not chosen by the agent</div>
      <b>${esc(label)}</b>${blocked}
      <div>Restored: <b>${o.restored ? "yes" : "no"}</b> · registration ${pct(o.registration_rate)} · app ${pct(o.application_ack_rate)}</div>
      <div>Profile changes ${o.profile_changes} · unnecessary ${o.unnecessary_profile_changes} · downtime ${o.downtime_minutes} min</div></div>`;
  } catch (e) { out.textContent = `Failed: ${e.message}`; }
}

function setBusy(b) {
  busy = b;
  $("thinking").hidden = !b;
  updateButtons();
}

function updateButtons() {
  const can = current && !current.done && !current.awaiting_approval && !busy;
  $("btn-step").disabled = !can;
  $("btn-auto").disabled = !can;
}

// ------------------------------------------------------------------ render
function render(s) {
  current = s;
  const o = s.outcome, obs = s.observable;
  $("q").textContent = s.question;

  // fleet
  $("fleet-empty").hidden = true; $("fleet").hidden = false;
  $("f-devices").textContent = obs.affected_devices.toLocaleString();
  const status = o.restored ? ["up", "RESTORED"] : obs.escalated ? ["esc", "ESCALATED"] : ["down", "DEGRADED"];
  $("f-status").className = `status-pill ${status[0]}`; $("f-status").textContent = status[1];
  const reg = obs.attach_success_rate, app = obs.application_ack_rate;
  setBar("f-reg", reg); setBar("f-app", app);
  $("f-reg-t").textContent = pct(reg); $("f-app-t").textContent = pct(app);
  const n = 200, onReg = Math.round(reg * n), onApp = Math.round(app * n);
  $("f-dots").innerHTML = Array.from({ length: n }, (_, i) =>
    `<i class="${i < Math.min(onReg, onApp) ? "on" : i < Math.max(onReg, onApp) ? "half" : ""}"></i>`).join("");
  $("f-down").textContent = `${o.downtime_minutes} min`;
  $("f-pc").textContent = o.profile_changes; $("f-un").textContent = o.unnecessary_profile_changes;
  $("f-bl").textContent = o.blocked_actions; $("f-fe").textContent = o.forbidden_executions;

  // inspector: latest step, or the current option set before any step
  const last = s.steps[s.steps.length - 1];
  renderOptions(s, last);
  $("state-text").textContent = last ? last.state_text : s.state_text;

  // approval
  $("approval").hidden = !s.awaiting_approval;
  if (s.awaiting_approval) $("approval-plan").textContent = last.tool_output;

  // done banner
  const d = $("done");
  d.hidden = !s.done;
  if (s.done) {
    d.className = `done ${status[0]}`;
    d.textContent = o.restored
      ? `Service restored (${o.resolution}). Registration ${pct(reg)}, app telemetry ${pct(app)}.`
      : obs.escalated ? "Escalated to humans. No remote change attempted." : "Stopped without recovery.";
  }

  renderTrace(s);
  renderEuicc(s);
  $("events").innerHTML = s.events.length
    ? s.events.map((e) => `<li>t+${e.t_min}m ${esc(e.action)}: ${esc(e.result)}</li>`).join("")
    : `<li class="muted">No events yet.</li>`;
  updateButtons();
}

function setBar(id, v) { const el = $(id); el.style.width = `${Math.max(0, Math.min(1, v)) * 100}%`; el.className = v >= 0.95 ? "ok" : ""; }

function renderOptions(s, last) {
  const removed = last ? last.removed : {};
  const probs = (last && last.probabilities) || {};
  const rows = Object.entries(s.options).map(([name, meta]) => {
    const rm = removed[name];
    const chosen = last && last.choice === name;
    const p = probs[name];
    const policy = rm ? `<span class="why">removed: ${esc(rm)}</span>` : last ? "allowed" : "—";
    const pcell = p === undefined ? `<span class="muted">${rm ? "not offered" : "—"}</span>`
      : `<div class="pbar"><div class="bar"><i style="width:${p * 100}%"></i></div><span>${p.toFixed(3)}</span></div>`;
    return `<tr class="${rm ? "removed" : ""} ${chosen ? "chosen" : ""}">
      <td><code>${esc(name)}</code>${chosen ? '<span class="badge">CHOSEN</span>' : ""}<span class="tool">${esc(meta.tool)}</span></td>
      <td>${policy}</td><td>${pcell}</td></tr>`;
  });
  $("opts").innerHTML = rows.join("");
  $("meta").innerHTML = last
    ? `<span>Confidence <b>${last.confidence.toFixed(3)}</b></span>
       <span>Evidence sufficient (noul) <b>${last.evidence_sufficient == null ? "—" : last.evidence_sufficient.toFixed(3)}</b></span>
       <span>Latency <b>${last.decider_latency_ms == null ? "—" : Math.round(last.decider_latency_ms) + " ms"}</b></span>
       <span>Model <b>${esc(last.model)}</b></span>
       <span>Ran <b>${esc(last.tool || "nothing")}</b></span>`
    : "Press Next step to ask Decider.";
}

function renderTrace(s) {
  $("trace").innerHTML = s.steps.length ? s.steps.map((t, i) => {
    const appr = t.approval ? ` · approval: <b>${esc(t.approval)}</b>` : "";
    const after = `reg ${pct(t.after.registration_rate)} · app ${pct(t.after.application_ack_rate)}`;
    return `<li><div class="row"><b>Step ${i + 1}</b>
      <span class="muted">${t.allowed.length} allowed, ${Object.keys(t.removed).length} removed</span>
      <span class="arrow">→</span><code>${esc(t.choice)}</code>
      <span class="muted">(conf ${t.confidence.toFixed(3)})</span>
      <span class="arrow">→</span><code>${esc(t.tool || "nothing ran")}</code></div>
      <span class="res">${esc(t.tool_output)}${appr} · after: ${after}</span></li>`;
  }).join("") : `<li class="muted">No steps yet.</li>`;
}

function renderEuicc(s) {
  $("e-enabled").textContent = s.euicc.enabled;
  $("e-installed").textContent = s.euicc.installed.join(", ");
  $("guards").innerHTML = s.guards.map((g) =>
    `<li><span class="${g.ok ? "y" : "n"}" aria-hidden="true">${g.ok ? "✓" : "✗"}</span> ${esc(g.check)}
     <span class="sr-only">${g.ok ? "passes" : "fails"}</span></li>`).join("") +
    `<li><span class="${s.steps.some((t) => t.approval === "approved") ? "y" : "n"}" aria-hidden="true">${s.steps.some((t) => t.approval === "approved") ? "✓" : "✗"}</span> Human approval</li>`;
  const exec = s.steps.map((t) => t.profile_execution).filter(Boolean).pop();
  $("timeline").innerHTML = exec
    ? (exec.executed ? exec.timeline.map((x) => `<li>${esc(x)}</li>`).join("")
      : `<li style="color:var(--bad)">BLOCKED: ${esc(exec.blocked_reasons.join("; "))}</li>`)
    : `<li class="muted">No profile transition yet.</li>`;
}

// ------------------------------------------------------------------ wire up
$("btn-step").addEventListener("click", step);
$("btn-auto").addEventListener("click", runToEnd);
$("btn-approve").addEventListener("click", () => decide(true));
$("btn-reject").addEventListener("click", () => decide(false));
document.querySelectorAll("[data-cf]").forEach((b) => b.addEventListener("click", () => counterfactual(b.dataset.cf)));
loadHealth(); loadScenarios(); setInterval(loadHealth, 15000);
