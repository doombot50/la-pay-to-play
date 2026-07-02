/* LA Pay-to-Play — static SPA. Reads ./data/*.json built by paytoplay.build_site. */
'use strict';

const app = document.getElementById('app');
const cache = new Map();

async function load(path) {
  if (cache.has(path)) return cache.get(path);
  const res = await fetch(`data/${path}`);
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  const data = await res.json();
  cache.set(path, data);
  return data;
}

// ── formatting ────────────────────────────────────────────────────────────
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
function money(n) {
  n = Number(n) || 0;
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(0) + 'K';
  return '$' + n.toLocaleString('en-US', { maximumFractionDigits: 0 });
}
const moneyFull = (n) => '$' + (Number(n) || 0).toLocaleString('en-US', { maximumFractionDigits: 0 });
const scoreClass = (s) => (s >= 60 ? 'hi' : s >= 35 ? 'md' : 'lo');
const cleanOffice = (o) => String(o ?? '').replace(/\s*--\s*/g, ' ').replace(/\s+/g, ' ').trim();
const officeLabel = (o) => (o && o !== '(unmapped)' ? cleanOffice(o) : 'a controlling office');

// ── disclaimer + helpers ───────────────────────────────────────────────────
const disclaimerBar = (text) => `<div class="disclaimer">⚠️ <div><b>Correlation, not proof.</b> ${esc(text)}</div></div>`;

function components(c) {
  const items = [
    ['Money', c.money], ['Control', c.control], ['Timing', c.timing], ['Match', c.match],
  ];
  return `<div class="components">${items.map(([l, v]) => `
    <div class="comp"><div class="cl">${l}</div><div class="cv">${(v ?? 0).toFixed(2)}</div>
    <div class="bar"><span style="width:${Math.round((v ?? 0) * 100)}%"></span></div></div>`).join('')}</div>`;
}

// ── views ──────────────────────────────────────────────────────────────────
async function renderHome() {
  const [meta, board] = await Promise.all([load('meta.json'), load('leaderboard.json')]);
  const [cFrom, cTo] = meta.coverage.contracts;
  app.innerHTML = `
    ${disclaimerBar(meta.disclaimer)}
    <h1 class="page">Where contractor money meets the officials who steer contracts</h1>
    <p class="lede">Louisiana companies that hold state contracts <b>and</b> donated to the
      elected official who controls the agency awarding them. This is a deliberately high
      bar — a short list of genuine leads, not every contractor who gives. Ranked by a
      transparent concern score; every figure links to a public filing.</p>
    <div class="stat-row">
      <div class="stat"><div class="v">${board.length}</div><div class="l">Flagged relationships</div></div>
      <div class="stat"><div class="v">${meta.counts.companies}</div><div class="l">Companies</div></div>
      <div class="stat"><div class="v">${meta.counts.offices}</div><div class="l">Offices</div></div>
      <div class="stat"><div class="v">${meta.counts.contracts_total.toLocaleString()}</div><div class="l">Contracts ${esc(cFrom?.slice(0,4))}–${esc(cTo?.slice(0,4))}</div></div>
    </div>
    <div class="lb">${board.map(lbRow).join('')}</div>`;
  app.querySelectorAll('.lb-row').forEach((el) =>
    el.addEventListener('click', () => { location.hash = `#/vendor/${el.dataset.id}`; }));
}

function lbRow(r) {
  return `<div class="lb-row" data-id="${esc(r.vendor_id)}">
    <div class="score-badge score-${scoreClass(r.concern_score)}">${Math.round(r.concern_score)}</div>
    <div>
      <div class="company">${esc(r.company)}</div>
      <div class="chain">gave to <b>${esc(officeLabel(r.office))}</b> · holds contracts from <b>${esc(r.agency || 'the state')}</b></div>
    </div>
    <div class="lb-figs">
      <div class="fig in">${money(r.donation_total)}</div><div class="lbl">donated</div>
      <div class="fig out">${money(r.contract_total)}</div><div class="lbl">contracts</div>
    </div></div>`;
}

function chainCard(v) {
  const steps = [
    ['', `<div class="node">${esc(v.company)}</div>`, ''],
    ['donated', `<div class="node">campaigns for ${esc(officeLabel(v.office))}</div>`, `<span class="chain-amt in" style="color:var(--money-in)">${moneyFull(v.donation_total)}</span>`],
    ['who controls', `<div class="node">${esc(v.agency || 'the awarding agency')}<div class="sub">state contracting authority</div></div>`, ''],
    ['which awarded', `<div class="node">${esc(v.company)}<div class="sub">${v.contract_count} contract${v.contract_count === 1 ? '' : 's'}</div></div>`, `<span class="chain-amt" style="color:var(--money-out)">${moneyFull(v.contract_total)}</span>`],
  ];
  return `<div class="card chain-card">${steps.map(([rel, node, amt]) => `
    <div class="chain-step"><div class="rel">${rel || '↓'}</div>
      <div>${node} ${amt}</div></div>`).join('')}</div>`;
}

async function renderVendor(id) {
  let v;
  try { v = await load(`vendor/${id}.json`); }
  catch { app.innerHTML = `<a class="back" href="#/">← Leaderboard</a><p class="loading">Company not found.</p>`; return; }
  app.innerHTML = `
    <a class="back" href="#/">← Leaderboard</a>
    ${disclaimerBar(v.disclaimer)}
    <h1 class="page">${esc(v.company)}</h1>
    <p class="lede">Holds <b>${moneyFull(v.contract_total)}</b> in contracts from
      <b>${esc(v.agency || 'the awarding agency')}</b> and donated
      <b>${moneyFull(v.donation_total)}</b> to campaigns for <b>${esc(officeLabel(v.office))}</b>,
      which helps control that agency.</p>
    <div class="section-h">The money chain</div>
    ${chainCard(v)}
    <div class="section-h">Concern score · ${Math.round(v.concern_score)}/100</div>
    ${components(v.components)}
    <div class="section-h">State contracts (${v.contracts.length}, all agencies)</div>
    ${tableContracts(v.contracts)}
    <div class="section-h">Campaign donations (top ${v.gifts.length})</div>
    ${tableGifts(v.gifts)}`;
}

function tableContracts(rows) {
  if (!rows.length) return `<p class="muted">No contracts on file.</p>`;
  return `<table class="data"><thead><tr><th>Agency</th><th>Approved</th><th class="num">Amount</th><th>Source</th></tr></thead><tbody>${
    rows.map((c) => `<tr><td>${esc(c.agency)}</td><td class="num">${esc(c.award_date)}</td>
      <td class="num">${moneyFull(c.amount)}</td>
      <td class="src"><a href="${esc(c.source_url)}" target="_blank" rel="noopener">Act 87 report ↗</a></td></tr>`).join('')}</tbody></table>`;
}
function tableGifts(rows) {
  if (!rows.length) return `<p class="muted">No itemized donations found.</p>`;
  return `<table class="data"><thead><tr><th>Recipient</th><th>Office</th><th class="num">Date</th><th class="num">Amount</th><th>Source</th></tr></thead><tbody>${
    rows.map((g) => `<tr><td>${esc(g.recipient)}</td><td>${esc(cleanOffice(g.office)) || '<span class="muted">—</span>'}</td>
      <td class="num">${esc(g.date)}</td><td class="num">${moneyFull(g.amount)}</td>
      <td class="src">${g.source_url ? `<a href="${esc(g.source_url)}" target="_blank" rel="noopener">filing ↗</a>` : '—'}</td></tr>`).join('')}</tbody></table>`;
}

async function renderOffices() {
  const offices = await load('offices.json');
  app.innerHTML = `
    <h1 class="page">Officials & the contractors who fund them</h1>
    <p class="lede">Grouped by the elected office that controls contracting authority. Each company
      below both donated to campaigns for that office and holds contracts from agencies it influences.</p>
    ${offices.filter((o) => o.office !== '(unmapped)').map(officeCard).join('')}`;
  app.querySelectorAll('.lb-row').forEach((el) =>
    el.addEventListener('click', () => { location.hash = `#/vendor/${el.dataset.id}`; }));
}

function officeCard(o) {
  const total = o.companies.reduce((s, c) => s + c.donation_total, 0);
  return `<div class="section-h">${esc(o.office)} <span class="badge office">${esc(o.control || 'control')}</span>
      <span class="muted num" style="font-weight:500"> · ${money(total)} donated by ${o.companies.length} contractor${o.companies.length === 1 ? '' : 's'}</span></div>
    <div class="lb">${o.companies.sort((a, b) => b.concern_score - a.concern_score).map((c) => `
      <div class="lb-row" data-id="${esc(c.vendor_id)}">
        <div class="score-badge score-${scoreClass(c.concern_score)}">${Math.round(c.concern_score)}</div>
        <div><div class="company">${esc(c.company)}</div><div class="chain">contracts from <b>${esc(c.agency)}</b></div></div>
        <div class="lb-figs"><div class="fig in">${money(c.donation_total)}</div><div class="lbl">donated</div>
          <div class="fig out">${money(c.contract_total)}</div><div class="lbl">contracts</div></div>
      </div>`).join('')}</div>`;
}

async function renderSearch(q) {
  const idx = await load('search.json');
  const ql = q.toLowerCase().trim();
  const hits = ql ? idx.filter((r) => r.name.toLowerCase().includes(ql)).slice(0, 60) : [];
  app.innerHTML = `
    <a class="back" href="#/">← Leaderboard</a>
    <h1 class="page">Search</h1>
    <p class="lede">${hits.length} result${hits.length === 1 ? '' : 's'} for “${esc(q)}”.</p>
    <div class="search-results">${hits.map((r) => `
      <div class="sr" data-type="${r.type}" data-id="${esc(r.id)}">
        <span>${esc(r.name)}</span><span class="badge office">${r.type}</span></div>`).join('') || '<p class="muted">No matches.</p>'}</div>`;
  app.querySelectorAll('.sr').forEach((el) => el.addEventListener('click', () => {
    location.hash = el.dataset.type === 'vendor'
      ? `#/vendor/${el.dataset.id}` : `#/office/${encodeURIComponent(el.dataset.id)}`;
  }));
}

async function renderOffice(name) {
  const offices = await load('offices.json');
  const o = offices.find((x) => x.office === name);
  if (!o) { location.hash = '#/offices'; return; }
  app.innerHTML = `<a class="back" href="#/offices">← Officials</a>${officeCard(o)}`;
  app.querySelectorAll('.lb-row').forEach((el) =>
    el.addEventListener('click', () => { location.hash = `#/vendor/${el.dataset.id}`; }));
}

async function renderMethodology() {
  const meta = await load('meta.json');
  const t = meta.thresholds;
  app.innerHTML = `
    <a class="back" href="#/">← Leaderboard</a>
    <div class="prose">
      <h1 class="page">Methodology</h1>
      <p>${esc(meta.disclaimer)}</p>
      <h2>What this is</h2>
      <p>This tool joins two public datasets that share no common key: Louisiana state
        <b>contracts</b> (the Division of Administration's Act 87 monthly reports) and
        <b>campaign donations</b> (the Louisiana Ethics Administration). A "flagged relationship"
        is a company that both holds state contracts and donated to campaigns for an elected
        official who controls the agency awarding those contracts.</p>
      <h2>The concern score</h2>
      <p>Each relationship gets a 0–100 score, always shown with its four components:
        <b>money</b> (log-scaled, both sides must be material), <b>control</b> (does the office
        the company funded actually control the awarding agency?), <b>timing</b> (donations
        clustered near contract awards), and <b>match</b> (name-match confidence). A weak match
        caps the whole score — no black box.</p>
      <h2>Important limitations</h2>
      <p>The Ethics contributions data carries no employer or street address, and contract
        reports carry no vendor address — so matching is <b>name-based</b>. We publish only
        strong organization-to-organization name matches (confidence ≥ ${t.publish_confidence})
        where both the contract (≥ ${moneyFull(t.min_contract_usd)}) and donations
        (≥ ${moneyFull(t.min_donation_usd)}) are material. Borderline matches are held for
        review and never shown here. We cannot detect a person who donated personally and whose
        company received a contract unless the company is named after them.</p>
      <h2>Sources</h2>
      <p>Contracts: <a href="https://checkbook.la.gov/contracts/index.cfm" target="_blank" rel="noopener">checkbook.la.gov</a> ·
         Donations: <a href="https://www.ethics.la.gov/" target="_blank" rel="noopener">ethics.la.gov</a>.
         Generated ${esc(meta.generated)}.</p>
    </div>`;
}

// ── router ─────────────────────────────────────────────────────────────────
async function router() {
  const hash = location.hash || '#/';
  const [, route, arg] = hash.match(/^#\/([^/]*)\/?(.*)$/) || [, '', ''];
  document.querySelectorAll('#nav a').forEach((a) =>
    a.classList.toggle('active', a.getAttribute('href') === (route ? `#/${route}` : '#/')));
  try {
    if (route === '' ) await renderHome();
    else if (route === 'vendor') await renderVendor(arg);
    else if (route === 'offices') await renderOffices();
    else if (route === 'office') await renderOffice(decodeURIComponent(arg));
    else if (route === 'search') await renderSearch(decodeURIComponent(arg));
    else if (route === 'methodology') await renderMethodology();
    else await renderHome();
  } catch (e) {
    app.innerHTML = `<p class="loading">Couldn't load data (${esc(e.message)}). Run <code>make pipeline && python -m paytoplay.build_site</code>.</p>`;
  }
  window.scrollTo(0, 0);
}

const searchEl = document.getElementById('search');
let stim;
searchEl.addEventListener('input', () => {
  clearTimeout(stim);
  stim = setTimeout(() => {
    const q = searchEl.value.trim();
    if (q) location.hash = `#/search/${encodeURIComponent(q)}`;
  }, 250);
});

window.addEventListener('hashchange', router);
router();
