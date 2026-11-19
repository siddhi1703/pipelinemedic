"""Static monitoring dashboard built from the JSON artifacts.

Read-only reporting: it never runs repairs and is never an input to the agent or
the verifier. The output is one self-contained HTML file with the data embedded,
so it opens from disk with no server or network access.
"""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

SOURCES = {
    "baseline": "baseline.json",
    "pilot": "pilot_results.json",
    "heldout": "heldout_results.json",
    "checker": "checker_challenges.json",
    "live": "claude_pilot_results.json",
    "candidates": "candidate_experiment.json",
    "demo": "demo.json",
}


def collect(artifacts):
    artifacts = Path(artifacts)
    data = {}
    for key, name in SOURCES.items():
        path = artifacts / name
        try:
            data[key] = json.loads(path.read_text()) if path.exists() else None
        except ValueError:
            data[key] = None
    data["generated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return data


def build(artifacts="artifacts", output=None):
    output = Path(output) if output else Path(artifacts) / "dashboard.html"
    payload = json.dumps(collect(artifacts)).replace("</", "<\\/")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(TEMPLATE.replace("__DATA__", payload), encoding="utf-8")
    return output


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PipelineMedic Monitor</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--ink:#1d1d1b;--muted:#6b6b66;--line:#e4e3de;
--ok:#2f7d4f;--ok-bg:#e3f1e8;--warn:#9a6a00;--warn-bg:#fbf0d6;--bad:#b3362c;--bad-bg:#f8e1de;--accent:#2b5c9e}
@media (prefers-color-scheme:dark){:root{--bg:#141413;--card:#1e1e1c;--ink:#ecebe6;--muted:#9c9b94;--line:#33322f;
--ok:#6cc48f;--ok-bg:#1d3326;--warn:#e0b450;--warn-bg:#3a2f14;--bad:#ef8a80;--bad-bg:#3d1f1c;--accent:#7fa8e0}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:24px 16px 64px}
h1{font-size:22px;margin:0}h2{font-size:15px;margin:0 0 12px}
.sub{color:var(--muted);font-size:13px}
header{display:flex;justify-content:space-between;align-items:flex-end;gap:12px;flex-wrap:wrap;margin-bottom:20px}
.grid{display:grid;gap:12px}.kpis{grid-template-columns:repeat(auto-fit,minmax(180px,1fr));margin-bottom:12px}
.two{grid-template-columns:repeat(auto-fit,minmax(min(420px,100%),1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;min-width:0}
.kpi .v{font-size:24px;font-weight:600;font-variant-numeric:tabular-nums}.kpi .l{color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
section{margin-top:12px}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:7px 8px;overflow-wrap:anywhere;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:500;font-size:12px}
.scroll{overflow-x:auto}.tall{max-height:420px;overflow:auto}
.pill{display:inline-block;padding:1px 8px;border-radius:99px;font-size:12px;font-weight:500;white-space:nowrap}
.accept{color:var(--ok);background:var(--ok-bg)}.human_review{color:var(--warn);background:var(--warn-bg)}
.reject,.error{color:var(--bad);background:var(--bad-bg)}
.empty{color:var(--muted);font-style:italic}
.bar{display:flex;height:14px;border-radius:4px;overflow:hidden;background:var(--line);min-width:120px}
.bar span{display:block;height:100%}
.legend{display:flex;gap:14px;font-size:12px;color:var(--muted);margin-bottom:8px;flex-wrap:wrap}
.legend i{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:5px;vertical-align:-1px}
.filters{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:10px}
select{background:var(--card);color:var(--ink);border:1px solid var(--line);border-radius:6px;padding:4px 8px;font:inherit}
code{font-size:12px}
.small{font-size:12px;color:var(--muted)}
</style>
</head>
<body>
<main>
<header>
  <div><h1>PipelineMedic Monitor</h1><div class="sub">Repair decisions, review queue and verifier health from <code>artifacts/</code></div></div>
  <div class="sub" id="gen"></div>
</header>
<div class="grid kpis" id="kpis"></div>
<section class="card"><h2>Scorecard</h2><div class="scroll" id="score"></div></section>
<section class="grid two">
  <div class="card"><h2>Human-review queue</h2><div class="tall" id="queue"></div></div>
  <div class="card"><h2>Outcomes by fault family</h2><div class="scroll" id="families"></div></div>
</section>
<section class="grid two">
  <div class="card"><h2>Live agent</h2><div class="scroll" id="live"></div></div>
  <div class="card"><h2>1-vs-N candidates</h2><div class="scroll" id="cands"></div></div>
</section>
<section class="card"><h2>Verifier negative controls</h2><div class="scroll" id="checker"></div></section>
<section class="card"><h2>All decisions</h2>
  <div class="filters" id="filters"></div><div class="scroll tall" id="decisions"></div></section>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pill = d => `<span class="pill ${esc(d)}">${esc(String(d).replace('_',' '))}</span>`;
const missing = cmd => `<p class="empty">Not run yet: <code>./run_local.sh ${cmd}</code></p>`;
const pct = (a, b) => b ? `${a}/${b}` : '—';
const money = v => v == null ? '—' : 'R$ ' + Number(v).toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2});
const usd = v => v == null ? '—' : '$' + Number(v).toFixed(3);
const table = (head, rows) => rows.length
  ? `<table><thead><tr>${head.map(h => `<th>${h}</th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr>${r.map(c => `<td>${c}</td>`).join('')}</tr>`).join('')}</tbody></table>`
  : '<p class="empty">Nothing to show.</p>';

$('gen').textContent = 'Generated ' + D.generated_at;

// KPIs
(() => {
  const m = D.baseline?.metrics, v = D.baseline?.verdict?.decision;
  const live = (D.live?.cases || []).reduce((s, c) => s + (c.estimated_cost_usd || 0), 0)
    + (D.candidates?.results || []).reduce((s, r) => s + (r.total_cost_usd || 0), 0);
  const wrong = ['pilot', 'heldout'].reduce((s, k) => s + (D[k]?.summary?.fixed_rules_with_verifier?.incorrect_acceptances || 0), 0);
  const k = [
    ['Orders', m ? m.order_count.toLocaleString() : '—'],
    ['Payment total', m ? money(m.payment_total) : '—'],
    ['Late delivery rate', m?.late_delivery_rate != null ? (m.late_delivery_rate * 100).toFixed(2) + '%' : '—'],
    ['Baseline verdict', v ? pill(v) : '—'],
    ['Wrong acceptances (verified)', String(wrong)],
    ['Live agent spend', usd(live)],
  ];
  $('kpis').innerHTML = k.map(([l, v]) => `<div class="card kpi"><div class="l">${l}</div><div class="v">${v}</div></div>`).join('');
})();

// Scorecard
(() => {
  const rows = [];
  const names = {unrepaired: 'Unrepaired', fixed_rules: 'Fixed rules', fixed_rules_with_verifier: 'Fixed rules + verifier'};
  for (const [key, label] of [['pilot', 'Development pilot'], ['heldout', 'Held-out']]) {
    const s = D[key]?.summary; if (!s) continue;
    for (const [m, x] of Object.entries(s))
      rows.push([label, names[m] || m, pct(x.correct_recoveries, x.repairable_cases), pct(x.appropriate_reviews, x.review_cases),
        x.incorrect_acceptances ? `<b style="color:var(--bad)">${x.incorrect_acceptances}</b>` : '0', x.mean_runtime_seconds.toFixed(2) + 's']);
  }
  for (const [label, run] of [['Agent alone', 'agent_alone'], ['Agent + verifier', 'agent_with_verifier']]) {
    const cs = (D.live?.cases || []).filter(c => c.runs);
    if (!cs.length) continue;
    const rep = cs.filter(c => c.family !== 'ambiguous'), rev = cs.filter(c => c.family === 'ambiguous');
    const wrong = cs.filter(c => c.runs[run].incorrect_acceptance).length;
    rows.push(['Live smoke cases', label, pct(rep.filter(c => c.runs[run].correct_recovery).length, rep.length),
      pct(rev.filter(c => c.runs[run].appropriate_review).length, rev.length),
      wrong ? `<b style="color:var(--bad)">${wrong}</b>` : '0', '—']);
  }
  $('score').innerHTML = rows.length ? table(['Suite', 'Method', 'Correct recoveries', 'Appropriate reviews', 'Wrong acceptances', 'Mean runtime'], rows) : missing('evaluate');
})();

// Human-review queue
(() => {
  const q = [];
  for (const [key, label] of [['pilot', 'Pilot'], ['heldout', 'Held-out']])
    for (const c of D[key]?.cases || [])
      if (c.method === 'fixed_rules_with_verifier' && c.decision === 'human_review')
        q.push([label, esc(c.scenario), esc((c.failures || [])[0] || '—')]);
  for (const c of D.live?.cases || [])
    if (c.runs?.agent_with_verifier?.decision === 'human_review')
      q.push(['Live agent', esc(c.family), esc(c.plan?.reason || (c.runs.agent_with_verifier.failures || [])[0] || '—')]);
  if (D.demo?.decision?.decision === 'human_review')
    q.push(['Demo', esc(D.demo.fault), esc((D.demo.decision.failures || [])[0] || D.demo.plan?.reason || '—')]);
  $('queue').innerHTML = (D.pilot || D.heldout || D.live)
    ? `<p class="small">${q.length} item${q.length === 1 ? '' : 's'} escalated instead of auto-repaired.</p>` + table(['Source', 'Case', 'Reason'], q)
    : missing('evaluate');
})();

// Outcomes by family
(() => {
  const colors = {accept: 'var(--ok)', human_review: 'var(--warn)', reject: 'var(--bad)'};
  const out = [];
  for (const [key, label] of [['pilot', 'Pilot'], ['heldout', 'Held-out']]) {
    const cases = D[key]?.cases || [];
    const fams = [...new Set(cases.map(c => c.family))];
    for (const f of fams) for (const m of ['unrepaired', 'fixed_rules_with_verifier']) {
      const sel = cases.filter(c => c.family === f && c.method === m);
      const n = {accept: 0, human_review: 0, reject: 0};
      sel.forEach(c => n[c.decision] = (n[c.decision] || 0) + 1);
      const bar = Object.entries(n).filter(([, v]) => v).map(([d, v]) => `<span title="${d}: ${v}" style="width:${100 * v / sel.length}%;background:${colors[d]}"></span>`).join('');
      out.push([`${label} · ${esc(f)}`, m === 'unrepaired' ? 'unrepaired' : 'verified', `<div class="bar">${bar}</div>`]);
    }
  }
  $('families').innerHTML = out.length
    ? `<div class="legend"><span><i style="background:var(--ok)"></i>accept</span><span><i style="background:var(--warn)"></i>human review</span><span><i style="background:var(--bad)"></i>reject</span></div>` + table(['Family', 'Run', 'Decisions'], out)
    : missing('evaluate');
})();

// Live agent
(() => {
  const cs = D.live?.cases;
  if (!cs) { $('live').innerHTML = missing('live-pilot'); return; }
  $('live').innerHTML = table(['Fault', 'Agent alone', 'With verifier', 'Correct', 'Latency', 'Cost'], cs.map(c => c.runs ? [
    esc(c.family), pill(c.runs.agent_alone.decision), pill(c.runs.agent_with_verifier.decision),
    (c.family === 'ambiguous' ? c.runs.agent_with_verifier.appropriate_review : c.runs.agent_with_verifier.correct_recovery) ? '✓' : '✗',
    c.claude_seconds.toFixed(1) + 's', usd(c.estimated_cost_usd)] : [esc(c.family), pill('error'), '', esc(c.error), '', '']));
})();

// Candidates
(() => {
  const rs = D.candidates?.results;
  if (!rs) { $('cands').innerHTML = missing('candidate-experiment'); return; }
  $('cands').innerHTML = table(['Fault', 'N', 'Candidates', '1 candidate', 'Best of N', 'Distinct plans', 'Cost'], rs.map(r => [
    esc(r.family), r.n, r.candidates.map(c => pill(c.decision)).join(' '),
    r.one_candidate.correct ? '✓' : '✗', r.best_of_n.correct ? '✓' : '✗', r.distinct_plans, usd(r.total_cost_usd)]));
})();

// Checker
(() => {
  const cs = D.checker?.cases;
  if (!cs) { $('checker').innerHTML = missing('checker-tests'); return; }
  $('checker').innerHTML = `<p class="small">Hand-built bad candidates. The full verifier should reject every one.</p>` +
    table(['Corruption', 'Full verifier', 'Schema-only', 'Caught by'], cs.map(c => [
      esc(c.challenge), pill(c.full.decision), pill(c.schema_only.decision), esc(c.full.failures.join('; '))]));
})();

// All decisions with filters
(() => {
  const all = [];
  for (const [key, label] of [['pilot', 'Pilot'], ['heldout', 'Held-out']])
    for (const c of D[key]?.cases || []) all.push({suite: label, ...c});
  if (!all.length) { $('decisions').innerHTML = missing('evaluate'); return; }
  const opts = k => ['all', ...new Set(all.map(r => r[k]))];
  const keys = ['suite', 'method', 'decision'];
  $('filters').innerHTML = keys.map(k => `<select data-k="${k}">${opts(k).map(o => `<option>${esc(o)}</option>`).join('')}</select>`).join('');
  const render = () => {
    const f = Object.fromEntries([...document.querySelectorAll('#filters select')].map(s => [s.dataset.k, s.value]));
    const rows = all.filter(r => keys.every(k => f[k] === 'all' || r[k] === f[k]));
    $('decisions').innerHTML = `<p class="small">${rows.length} of ${all.length} runs</p>` + table(['Suite', 'Scenario', 'Method', 'Decision', 'Correct', 'Detail'], rows.map(r => [
      r.suite, esc(r.scenario), esc(r.method), pill(r.decision),
      r.correct_recovery || r.appropriate_review ? '✓' : (r.incorrect_acceptance ? '<b style="color:var(--bad)">wrong</b>' : ''),
      `<span class="small">${esc((r.failures || [])[0] || '')}</span>`]));
  };
  document.querySelectorAll('#filters select').forEach(s => s.addEventListener('change', render));
  render();
})();
</script>
</body>
</html>
"""
