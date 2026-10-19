// SIMShift Recovery Decision Inspector. Vanilla JS; every value shown comes from the API, nothing is invented here.
"use strict";

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const pct = (x) => `${(x * 100).toFixed(1)}%`;
const num = (x, d = 2) => (typeof x === "number" ? x.toFixed(d) : "—");

let current = null;
let busy = false;

async function api(path, body) {
  const r = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
}

async function loadScenarios() {
  const list = await api("/api/scenarios");
  $("scenarios").innerHTML = list.map((s) => `
    <div role="listitem"><button class="scn" aria-pressed="false" data-id="${esc(s.id)}">
      <b>${esc(s.id)}</b><span>${esc(s.incident)} · ${esc(s.country)} · ${s.devices.toLocaleString()} devices</span>
    </button></div>`).join("");
  document.querySelectorAll(".scn").forEach((b) => b.addEventListener("click", () => start(b.dataset.id)));
}

async function start(id) {
  if (busy) return;
  document.querySelectorAll(".scn").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.id === id)));
  $("cf-out").innerHTML = "";
  $("explain").textContent = "Bedrock writes a short summary of the trace for a NOC engineer.";
  try { render(await api("/api/incidents", { scenario: id })); } catch (e) { alert(e.message); }
}

async function act(action, body = {}) {
  setBusy(true, action === "step");
  try { return await api(`/api/incidents/${current.id}/${action}`, body); }
  finally { setBusy(false); }
}

async function step() {
  if (!current || busy) return false;
  try { render(await act("step")); return true; } catch (e) { alert(`Step failed: ${e.message}`); return false; }
}

async function runToEnd() {
  while (current && !current.done && !current.pending_approval) {
    if (!(await step())) break; // stop on any error instead of looping
  }
}

async function decide(approved) {
  try { render(await act("approval", { approved })); } catch (e) { alert(e.message); }
}

async function explain() {
  $("explain").textContent = "Asking Bedrock…";
  try { $("explain").textContent = (await act("explain")).explanation.replaceAll("**", ""); } catch (e) { $("explain").textContent = e.message; }
}

async function counterfactual(option) {
  if (!current) return;
  $("cf-out").textContent = "Running on a clone…";
  try {
    const cf = await act("counterfactual", { option });
    const tr = cf.result.transition;
    const blocked = cf.result.gate && !cf.result.gate.allowed
      ? `<div style="color:var(--bad)"><b>BLOCKED by the gate:</b> ${esc(cf.result.gate.failed.join(", "))}</div>` : "";
    $("cf-out").innerHTML = `<div class="cf-card"><div class="label">Counterfactual · not chosen by the agent</div>
      <b>What if: <code>${esc(option)}</code></b>
      ${cf.excluded ? `<div class="why" style="color:var(--warn)">Policy would exclude it: ${esc(cf.excluded)}</div>` : ""}
      ${blocked}${tr ? `<div class="small">Transition: ${esc(tr.join(" → "))}</div>` : ""}
      <div>Restored: <b>${cf.restored ? "yes" : "no"}</b> · registration ${pct(cf.rates.attach_success_rate)} · app ${pct(cf.rates.app_ack_rate)}
      · +${cf.added_minutes} simulated min</div></div>`;
  } catch (e) { $("cf-out").textContent = `Failed: ${e.message}`; }
}

function setBusy(b, thinking = false) {
  busy = b;
  $("thinking").hidden = !(b && thinking);
  updateButtons();
}

function updateButtons() {
  const can = current && !current.done && !current.pending_approval && !busy;
  $("btn-step").disabled = !can;
  $("btn-auto").disabled = !can;
}

function render(s) {
  current = s;
  const o = s.outcome, obs = s.observable;
  const last = s.trace[s.trace.length - 1];
  const lastDecision = [...s.trace].reverse().find((t) => t.decision);
  $("q").textContent = s.question;

  const replay = s.decider_source.startsWith("replay");
  $("decider-chip").textContent = `Decider: ${replay ? "recorded real answers" : s.decider_source}`;
  $("decider-chip").className = `chip ${replay ? "replay" : "ok"}`;
  $("decider-chip").title = s.decider_source;
  $("bedrock-chip").textContent = s.bedrock ? "Bedrock: on" : "Bedrock: off";
  $("explain-panel").hidden = !s.bedrock;

  $("fleet-empty").hidden = true; $("fleet").hidden = false;
  $("f-devices").textContent = obs.affected_devices.toLocaleString();
  const escalated = s.done && !o.restored && last && last.tool === "defer_or_escalate";
  const status = o.restored ? ["up", "RESTORED"] : escalated ? ["esc", "ESCALATED"] : ["down", "DEGRADED"];
  $("f-status").className = `status-pill ${status[0]}`; $("f-status").textContent = status[1];
  const reg = obs.attach_success_rate, app = obs.app_ack_rate;
  setBar("f-reg", reg); setBar("f-app", app);
  $("f-reg-t").textContent = pct(reg); $("f-app-t").textContent = pct(app);
  const n = 200, onReg = Math.round(reg * n), onApp = Math.round(app * n);
  $("f-dots").innerHTML = Array.from({ length: n }, (_, i) =>
    `<i class="${i < Math.min(onReg, onApp) ? "on" : i < Math.max(onReg, onApp) ? "half" : ""}"></i>`).join("");
  $("f-op").textContent = `${o.serving_operator} (${o.active_profile})`;
  $("f-min").textContent = o.simulated_minutes;
  $("f-pc").textContent = o.profile_changes;
  $("f-bl").textContent = o.blocked_calls;
  $("f-fe").textContent = o.forbidden_executions;

  renderOptions(s, lastDecision && lastDecision.decision);
  $("state").textContent = JSON.stringify(lastDecision ? lastDecision.decision.state : obs, null, 1);

  $("approval").hidden = !s.pending_approval;
  if (s.pending_approval) {
    const p = s.bedrock_plan;
    $("approval-plan").innerHTML = `Proposal <code>${esc(s.pending_approval)}</code>: enable <b>${esc(s.gate.target)}</b>.` +
      (p && p.error ? `<br>${esc(p.error)} (advisory only; the checks above still apply).`
        : p ? `<br>Bedrock review: <b>${p.recommend_proceeding ? "proceed" : "do not proceed"}</b>. ${esc(p.rationale)}` : "");
  }

  const d = $("done");
  d.hidden = !s.done;
  if (s.done) {
    d.className = `done ${status[0]}`;
    const end = s.transition && s.transition[s.transition.length - 1];
    d.textContent = o.restored ? `Service restored. Registration ${pct(reg)}, app telemetry ${pct(app)}.`
      : escalated && ["UNCONFIRMED", "ROLLBACK_FAILED"].includes(end)
        ? `Escalated to a human: the profile switch ended ${end}, so the eIM cannot vouch for the device state.`
      : escalated ? "Escalated to a human with the collected evidence. No unverified remote change was made."
      : "Stopped without recovery.";
  }

  renderTrace(s);
  renderEuicc(s);
  $("cf-buttons").innerHTML = Object.keys(s.options).map((opt) =>
    `<button class="secondary" data-cf="${esc(opt)}">What if: ${esc(opt)}</button>`).join("");
  document.querySelectorAll("[data-cf]").forEach((b) => b.addEventListener("click", () => counterfactual(b.dataset.cf)));
  $("events").innerHTML = s.events.length ? s.events.map((e) => `<li>${esc(e.kind)} ${esc(eventText(e))}</li>`).join("")
    : `<li class="muted">No events yet.</li>`;
  updateButtons();
}

function eventText(e) {
  if (e.result) return e.result.summary || e.result.reason || "";
  if (e.kind === "eim_enable_profile" && e.ok) return `ok → ${e.to_profile}${e.result_reported ? "" : " (no result reported to the eIM)"}`;
  if (e.kind.startsWith("eim_")) return e.ok ? `ok → ${e.to_profile}` : `refused: ${e.reason}`;
  if (e.kind === "ipa_local_rollback") return `device rolled back ${e.from_profile} → ${e.to_profile} on its own`;
  if (e.kind === "operator_reselection") return e.ok ? `${e.from_operator} → ${e.to_operator}` : e.reason;
  return e.restored === undefined ? "" : `restored=${e.restored}`;
}

function setBar(id, v) { const el = $(id); el.style.width = `${Math.max(0, Math.min(1, v)) * 100}%`; el.className = v >= 0.95 ? "ok" : ""; }

function renderOptions(s, d) {
  const raw = (d && d.raw) || {};
  const probs = raw.probabilities || {};
  $("opts").innerHTML = Object.entries(s.options).map(([name, meta]) => {
    const rm = d && d.excluded[name];
    const chosen = d && raw.choice === name, ran = d && d.selected === name;
    const p = probs[name];
    const policy = rm ? `<span class="why">removed: ${esc(rm)}</span>` : d ? "offered" : "—";
    const pcell = p === undefined ? `<span class="muted">${rm ? "not offered" : "—"}</span>`
      : `<div class="pbar"><div class="bar"><i style="width:${p * 100}%"></i></div><span>${p.toFixed(3)}</span></div>`;
    return `<tr class="${rm ? "removed" : ""} ${chosen ? "chosen" : ""}">
      <td><code>${esc(name)}</code>${chosen ? '<span class="badge">DECIDER</span>' : ""}${ran ? '<span class="badge">RAN</span>' : ""}
      <span class="tool">${esc(meta.tool)}</span></td><td>${policy}</td><td>${pcell}</td></tr>`;
  }).join("");
  $("meta").innerHTML = d
    ? `<span>Confidence <b>${num(raw.confidence)}</b></span>
       <span>Route <b>${esc(d.route)}</b>: ${esc(d.reason)}</span>
       <span>Latency <b>${raw.latency_ms == null ? "—" : Math.round(raw.latency_ms) + " ms"}</b></span>
       <span>Model <b>${esc(raw.model || (raw.error ? "unavailable" : "no call needed"))}</b>${raw.replayed ? " (recorded)" : ""}</span>`
    : "Press Next step to ask Decider.";
}

function renderTrace(s) {
  $("trace").innerHTML = s.trace.length ? s.trace.map((t) => {
    const d = t.decision, raw = (d && d.raw) || {};
    const head = d ? `<span class="muted">${Object.keys(d.eligible).length} offered, ${Object.keys(d.excluded).length} removed</span>
        <span class="arrow">→</span> Decider <code>${esc(raw.choice || "—")}</code> <span class="muted">(conf ${num(raw.confidence)})</span>
        <span class="route ${esc(d.route)}">${esc(d.route)}</span>`
      : `<span class="muted">${esc(t.note)}</span>`;
    const res = typeof t.tool_result === "string" ? t.tool_result
      : (t.tool_result.result && t.tool_result.result.summary) || (t.tool_result.gate && (t.tool_result.executed
        ? `profile switch to ${t.tool_result.gate.target} ended ${t.tool_result.transition.at(-1)}`
        : `gate stopped at: ${t.tool_result.gate.failed.join(", ")}`)) || (t.tool_result.escalated ? "handed off to a human" : "");
    return `<li><div class="row"><b>Step ${t.step}</b> ${head}<span class="arrow">→</span><code>${esc(t.tool)}</code>
      <span class="muted">[${esc(t.tool_status)}]</span></div>
      <span class="res">${esc(res)} · after: reg ${pct(t.rates_after.attach_success_rate)} · app ${pct(t.rates_after.app_ack_rate)}</span></li>`;
  }).join("") : `<li class="muted">No steps yet.</li>`;
}

function renderEuicc(s) {
  $("e-enabled").textContent = s.profiles.active;
  $("e-installed").textContent = Object.entries(s.profiles.installed).map(([p, v]) => `${p} (${v.operators.join("/")})`).join(", ");
  $("guards").innerHTML = Object.entries(s.gate.checks).map(([k, ok]) =>
    `<li><span class="${ok ? "y" : "n"}" aria-hidden="true">${ok ? "✓" : "✗"}</span> ${esc(k.replaceAll("_", " "))}
     <span class="sr-only">${ok ? "passes" : "fails"}</span></li>`).join("") +
    `<li class="muted small">Target ${esc(s.gate.target)} · ${s.transition ? "last attempt" : "live preview, no approval yet"}</li>`;
  const path = s.transition;
  $("timeline").innerHTML = path
    ? path.map((x) => `<li style="color:var(--${["BLOCKED", "FAILED", "NOT_DELIVERED", "ROLLBACK_FAILED", "UNCONFIRMED"].includes(x) ? "bad" : x === "SUCCEEDED" ? "ok" : ["AWAITING_APPROVAL", "RESULT_PENDING"].includes(x) ? "warn" : "text"})">${esc(x)}</li>`).join("")
    : `<li class="muted">No profile transition yet.</li>`;
}

$("btn-step").addEventListener("click", step);
$("btn-auto").addEventListener("click", runToEnd);
$("btn-approve").addEventListener("click", () => decide(true));
$("btn-reject").addEventListener("click", () => decide(false));
$("btn-explain").addEventListener("click", explain);
loadScenarios();
