let currentConfig = null;
let pendingInitialWeights = {};

function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  setTimeout(() => el.classList.remove('show'), 2200);
}

function switchTab(name) {
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.id === name));
  document.querySelectorAll('.nav[data-tab]').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  if (name === 'gallery') loadGallery();
  if (name === 'winrecord') loadWinRecord();
  if (name === 'landscape') loadLandscape();
  if (name === 'tournament') loadBestPanel();
}

document.querySelectorAll('.nav[data-tab]').forEach(btn => btn.addEventListener('click', () => switchTab(btn.dataset.tab)));

// ---------- Tournament ----------
async function chooseDuel(winner) {
  document.getElementById('duel-content').innerHTML = '';
  setProgress(true, 0);
  document.getElementById('duel-status').textContent = '생성 중…';
  await fetch('/choose', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({winner}) });
  loadBestPanel(); // reflect the just-recorded choice immediately, don't wait for next images
  pollDuel();
}

async function startDuel() {
  document.getElementById('duel-content').innerHTML = '';
  setProgress(true, 0);
  document.getElementById('duel-status').textContent = '생성 중…';
  await fetch('/start', { method: 'POST' });
  pollDuel();
}

function setProgress(show, frac) {
  const wrap = document.getElementById('duel-progress');
  const bar = document.getElementById('duel-progress-bar');
  wrap.hidden = !show;
  if (show) bar.style.width = `${Math.round((frac || 0) * 100)}%`;
}

function weightBars(weights, excluded) {
  const bounds = currentConfig ? currentConfig.weight_bounds : [0.2, 1.6];
  const [lo, hi] = bounds;
  const rows = Object.entries(weights).map(([tag, w]) => {
    const frac = Math.max(0, Math.min(1, (w - lo) / (hi - lo)));
    const isOut = excluded && excluded.has(tag);
    const style = isOut ? ' style="opacity:.4;text-decoration:line-through;"' : '';
    return `<div class="bar-row"${style}><div><b>${tag}</b><div class="bar-track"><i style="width:${(frac*100).toFixed(0)}%"></i></div></div><div class="val">${w.toFixed(2)}</div></div>`;
  }).join('');
  return `<div class="bars">${rows}</div>`;
}

function duelCard(side, data) {
  return `<div class="choice-card" onclick="chooseDuel('${side}')">
    <span class="label">${side === 'left' ? 'A' : 'B'}</span>
    <img src="${data.image}" />
    <div class="choice-meta">${weightBars(data.weights)}</div>
  </div>`;
}

async function pollDuel() {
  const res = await fetch('/state');
  const s = await res.json();
  document.getElementById('round-badge').textContent = `${s.round} / ${s.max_rounds}`;

  const content = document.getElementById('duel-content');
  const status = document.getElementById('duel-status');

  if (s.status === 'needs_config') {
    setProgress(false);
    content.innerHTML = `<div class="empty-card">${s.error ? s.error + '<br/>' : ''}artist_tags 및 설정이 필요합니다.<br/><button class="primary" onclick="switchTab('settings')" style="margin-top:10px;">Settings로 이동</button></div>`;
    status.textContent = '';
    return;
  } else if (s.status === 'idle') {
    setProgress(false);
    content.innerHTML = `<div class="empty-card"><h2>준비됨</h2><p>설정이 완료되었습니다. Start를 누르면 첫 듀얼이 생성됩니다.</p><button class="primary" onclick="startDuel()" style="margin-top:10px;">▶ Start</button></div>`;
    status.textContent = '';
    loadBestPanel();
    return;
  } else if (s.status === 'ready') {
    setProgress(false);
    content.innerHTML = `<div class="pair-stage">${duelCard('left', s.left)}${duelCard('right', s.right)}</div>`;
    status.textContent = '더 마음에 드는 이미지를 클릭하세요.';
    loadBestPanel();
    return;
  } else if (s.status === 'generating') {
    setProgress(true, s.progress);
    status.textContent = '생성 중…';
  } else if (s.status === 'done') {
    setProgress(false);
    content.innerHTML = `<div class="empty-card"><h2>완료</h2><p>추정된 최적 가중치는 아래 패널을 확인하세요.</p><button class="primary" onclick="startDuel()" style="margin-top:10px;">더 진행하기</button></div>`;
    status.textContent = '';
    loadBestPanel();
    return;
  } else if (s.status === 'error') {
    setProgress(false);
    status.textContent = 'error: ' + s.error;
    content.innerHTML = `<div class="empty-card"><button class="primary" onclick="startDuel()">다시 시도</button></div>`;
    return;
  }
  setTimeout(pollDuel, 1200);
}

async function loadBestPanel() {
  const res = await fetch('/best');
  const data = await res.json();
  document.getElementById('best-observed').textContent = data.observed_pairs;
  const view = document.getElementById('best-weights-view');
  const excluded = new Set(data.excluded || []);
  view.innerHTML = data.observed_pairs ? weightBars(data.weights, excluded) : '<div style="color:var(--muted);font-size:12px;">아직 선택 기록이 없습니다 — 균등 가중치(1.0) 기준입니다.</div>';

  const confPct = Math.round((data.confidence || 0) * 100);
  document.getElementById('confidence-bar').style.width = confPct + '%';
  document.getElementById('confidence-pct').textContent = confPct + '%';

  const cutoffInput = document.getElementById('cutoff-threshold');
  if (document.activeElement !== cutoffInput) cutoffInput.value = data.cutoff;
  const resultEl = document.getElementById('cutoff-result');
  resultEl.textContent = excluded.size ? `프롬프트에서 제외됨: ${[...excluded].join(', ')}` : (data.cutoff > 0 ? '컷오프 미만 태그 없음' : '');
}

document.getElementById('copy-best').addEventListener('click', async () => {
  const res = await fetch('/best');
  const data = await res.json();
  try {
    await navigator.clipboard.writeText(data.artist_prompt);
    toast('작가 태그 복사됨 (' + data.observed_pairs + '개 선택 기반)');
  } catch (e) {
    toast('클립보드 접근 실패: ' + e.message);
  }
});

// ---------- Prompt cutoff (treat low-weight tags as absent, tag stays in search space) ----------
document.getElementById('cutoff-apply').addEventListener('click', async () => {
  const input = document.getElementById('cutoff-threshold');
  const threshold = parseFloat(input.value);
  if (Number.isNaN(threshold)) { document.getElementById('cutoff-result').textContent = '컷오프 값을 입력하세요.'; return; }
  await fetch('/prompt-cutoff', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ threshold }) });
  if (currentConfig) currentConfig.prompt_cutoff = threshold;
  toast(`컷오프 ${threshold} 적용됨`);
  loadBestPanel();
});

// ---------- Reset progress (keep tags/config, clear duel history) ----------
document.getElementById('s-reset').addEventListener('click', async () => {
  const ok = confirm('지금까지의 A/B 선택 기록과 라운드를 전부 지웁니다. 태그/프롬프트/설정은 유지됩니다.\n\n계속할까요?');
  if (!ok) return;
  await fetch('/reset', { method: 'POST' });
  toast('진행 상황 초기화됨');
  loadBestPanel();
  pollDuel();
});

// ---------- Gallery ----------
async function loadGallery() {
  const grid = document.getElementById('gallery-grid');
  grid.innerHTML = '로딩…';
  const res = await fetch('/history');
  const { history } = await res.json();
  if (!history.length) { grid.innerHTML = '<div class="empty-card">아직 생성된 이미지가 없습니다.</div>'; return; }
  const cards = [];
  for (const h of [...history].reverse()) {
    for (const side of ['left', 'right']) {
      const win = h.winner === side;
      const weightsText = Object.entries(h[side]).map(([t, w]) => `${t}:${w.toFixed(2)}`).join(', ');
      cards.push(`<div class="gallery-card ${win ? 'win' : ''}">
        <span class="tag ${win ? 'win' : ''}">${win ? 'WIN' : 'round ' + h.round}</span>
        <img src="${h[side + '_image']}" />
        <small>${weightsText}</small>
      </div>`);
    }
  }
  grid.innerHTML = `<div class="gallery-grid">${cards.join('')}</div>`;
}

// ---------- Win Record ----------
async function loadWinRecord() {
  const list = document.getElementById('winrecord-list');
  list.innerHTML = '로딩…';
  const res = await fetch('/history');
  const { history } = await res.json();
  if (!history.length) { list.innerHTML = '<div class="empty-card">기록 없음</div>'; return; }
  list.innerHTML = [...history].reverse().map(h => {
    const winWeights = h[h.winner];
    const text = Object.entries(winWeights).map(([t, w]) => `${t}:${w.toFixed(2)}`).join(', ');
    return `<div class="history-row"><span>round ${h.round} — <b>${h.winner.toUpperCase()}</b> 승</span><span>${text}</span></div>`;
  }).join('');
}

// ---------- Tag Wiki ----------
async function searchWiki() {
  const q = document.getElementById('wiki-q').value.trim();
  const category = document.getElementById('wiki-category').value;
  const results = document.getElementById('wiki-results');
  if (!q) { results.innerHTML = ''; return; }
  results.innerHTML = '검색 중…';
  const res = await fetch(`/wiki/search?q=${encodeURIComponent(q)}&category=${encodeURIComponent(category)}`);
  const data = await res.json();
  if (!data.available) { results.innerHTML = '<div class="empty-card">danbooru-wiki.sqlite3를 찾을 수 없습니다.</div>'; return; }
  if (!data.results.length) { results.innerHTML = '<div class="empty-card">결과 없음</div>'; return; }
  results.innerHTML = data.results.map(r => `<div class="wiki-result">
    <b>${r.tag}</b><span class="cat"> · ${r.category}${r.aliases.length ? ' · aka ' + r.aliases.slice(0,3).join(', ') : ''}</span>
    <p>${r.snippet}</p>
  </div>`).join('');
}
document.getElementById('wiki-search').addEventListener('click', searchWiki);
document.getElementById('wiki-q').addEventListener('keydown', e => { if (e.key === 'Enter') searchWiki(); });

// ---------- Loss Landscape ----------
function buildChart(series) {
  const w = 560, h = 110, pad = 6;
  const allY = series.mean.flatMap((m, i) => [m - series.std[i], m + series.std[i]]);
  const yMin = Math.min(...allY), yMax = Math.max(...allY);
  const yRange = (yMax - yMin) || 1;
  const n = series.xs.length;
  const xAt = i => pad + (i / (n - 1)) * (w - 2 * pad);
  const yAt = v => h - pad - ((v - yMin) / yRange) * (h - 2 * pad);

  const upper = series.mean.map((m, i) => `${xAt(i)},${yAt(m + series.std[i])}`);
  const lower = series.mean.map((m, i) => `${xAt(i)},${yAt(m - series.std[i])}`).reverse();
  const band = [...upper, ...lower].join(' ');
  const line = series.mean.map((m, i) => `${xAt(i)},${yAt(m)}`).join(' ');
  const bestFrac = (series.best - series.xs[0]) / (series.xs[n - 1] - series.xs[0]);
  const bestX = pad + bestFrac * (w - 2 * pad);

  return `<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none">
    <polygon points="${band}" fill="rgba(179,156,255,.18)" />
    <polyline points="${line}" fill="none" stroke="#a4f46b" stroke-width="2" />
    <line x1="${bestX}" y1="0" x2="${bestX}" y2="${h}" stroke="#ff9d66" stroke-width="1" stroke-dasharray="3,3" />
  </svg>`;
}

async function loadLandscape() {
  const el = document.getElementById('landscape-content');
  el.innerHTML = '계산 중…';
  const res = await fetch('/landscape');
  const data = await res.json();
  if (!data.ready) { el.innerHTML = '<div class="empty-card">아직 선택 기록이 부족합니다 (최소 1라운드 필요).</div>'; return; }
  el.innerHTML = `<div class="landscape-grid">${data.series.map(s => `
    <div class="landscape-card">
      <b>${s.tag}</b> <span style="color:var(--muted);font-size:11px;">best=${s.best.toFixed(2)}</span>
      ${buildChart(s)}
    </div>`).join('')}</div>`;
}
document.getElementById('landscape-refresh').addEventListener('click', loadLandscape);

// ---------- Settings ----------
async function loadSettings() {
  const res = await fetch('/config');
  const data = await res.json();
  currentConfig = data.config;
  pendingInitialWeights = { ...(data.config.initial_weights || {}) };
  const c = data.config;

  document.getElementById('provider-pill').textContent = c.use_live_novelai ? 'LIVE' : 'MOCK';
  document.getElementById('provider-pill').classList.toggle('live', !!c.use_live_novelai);

  const modelSel = document.getElementById('s-model');
  modelSel.innerHTML = data.models.map(m => `<option value="${m.id}">${m.label}</option>`).join('');
  const samplerSel = document.getElementById('s-sampler');
  samplerSel.innerHTML = data.samplers.map(s => `<option value="${s}">${s}</option>`).join('');
  const scheduleSel = document.getElementById('s-schedule');
  scheduleSel.innerHTML = data.noise_schedules.map(s => `<option value="${s}">${s}</option>`).join('');

  document.getElementById('s-token').value = c.novelai_token || '';
  document.getElementById('s-use-live').checked = !!c.use_live_novelai;
  modelSel.value = c.model;
  document.getElementById('s-artist-tags').value = (c.artist_tags || []).join('\n');
  document.getElementById('s-weight-min').value = c.weight_bounds[0];
  document.getElementById('s-weight-max').value = c.weight_bounds[1];
  document.getElementById('s-prompt-cutoff').value = c.prompt_cutoff || 0;
  document.getElementById('s-weight-budget').value = c.weight_budget_per_tag ?? 1.0;
  document.getElementById('s-reuse-threshold').value = c.reuse_threshold ?? 0.03;
  document.getElementById('s-base-prompt').value = c.base_prompt || '';
  document.getElementById('s-quality-prompt').value = c.quality_prompt || '';
  document.getElementById('s-negative-prompt').value = c.negative_prompt || '';
  document.getElementById('s-width').value = c.width;
  document.getElementById('s-height').value = c.height;
  document.getElementById('s-steps').value = c.steps;
  document.getElementById('s-scale').value = c.scale;
  document.getElementById('s-rescale').value = c.cfg_rescale;
  samplerSel.value = c.sampler;
  scheduleSel.value = c.noise_schedule;
  document.getElementById('s-variety').checked = !!c.variety_plus;
  document.getElementById('s-seed').value = c.seed;
  document.getElementById('s-max-rounds').value = c.max_rounds;
  document.getElementById('s-candidate-pool').value = c.candidate_pool;
}

async function saveSettings() {
  const body = {
    novelai_token: document.getElementById('s-token').value.trim(),
    use_live_novelai: document.getElementById('s-use-live').checked,
    model: document.getElementById('s-model').value,
    artist_tags: document.getElementById('s-artist-tags').value.split('\n').map(s => s.trim()).filter(Boolean),
    weight_min: parseFloat(document.getElementById('s-weight-min').value),
    weight_max: parseFloat(document.getElementById('s-weight-max').value),
    prompt_cutoff: parseFloat(document.getElementById('s-prompt-cutoff').value) || 0,
    weight_budget_per_tag: parseFloat(document.getElementById('s-weight-budget').value) || 0,
    reuse_threshold: parseFloat(document.getElementById('s-reuse-threshold').value) || 0,
    base_prompt: document.getElementById('s-base-prompt').value,
    quality_prompt: document.getElementById('s-quality-prompt').value,
    negative_prompt: document.getElementById('s-negative-prompt').value,
    width: parseInt(document.getElementById('s-width').value, 10),
    height: parseInt(document.getElementById('s-height').value, 10),
    steps: parseInt(document.getElementById('s-steps').value, 10),
    scale: parseFloat(document.getElementById('s-scale').value),
    cfg_rescale: parseFloat(document.getElementById('s-rescale').value),
    sampler: document.getElementById('s-sampler').value,
    noise_schedule: document.getElementById('s-schedule').value,
    variety_plus: document.getElementById('s-variety').checked,
    seed: parseInt(document.getElementById('s-seed').value, 10),
    max_rounds: parseInt(document.getElementById('s-max-rounds').value, 10),
    candidate_pool: parseInt(document.getElementById('s-candidate-pool').value, 10),
    initial_weights: pendingInitialWeights,
  };
  const res = await fetch('/config', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body) });
  const data = await res.json();
  const msg = document.getElementById('s-msg');
  if (data.ok) {
    const now = new Date().toLocaleTimeString('ko-KR');
    msg.style.color = '#8f8';
    msg.textContent = `✓ 저장됨 (${now}). 토큰 ${body.novelai_token ? body.novelai_token.length + '자 저장됨' : '비어있음'} · artist tags ${body.artist_tags.length}개.`;
    toast('설정 저장됨');
    await loadSettings();
    pollDuel(); // refresh the round badge / provider pill without leaving this tab
  } else {
    msg.style.color = '#f88';
    msg.textContent = data.error || 'save failed';
  }
}
document.getElementById('s-save').addEventListener('click', saveSettings);

// ---------- Prompt import (paste NAI prompt -> split into artist / quality / situation) ----------
function mergeLines(box, newTags) {
  const existing = box.value.split('\n').map(s => s.trim()).filter(Boolean);
  const keys = new Set(existing.map(s => s.toLowerCase()));
  let added = 0;
  for (const t of newTags) {
    if (!keys.has(t.toLowerCase())) { existing.push(t); keys.add(t.toLowerCase()); added++; }
  }
  box.value = existing.join('\n');
  return added;
}

function mergeCommaList(box, newTags) {
  const existing = box.value.split(',').map(s => s.trim()).filter(Boolean);
  const keys = new Set(existing.map(s => s.toLowerCase()));
  let added = 0;
  for (const t of newTags) {
    if (!keys.has(t.toLowerCase())) { existing.push(t); keys.add(t.toLowerCase()); added++; }
  }
  box.value = existing.join(', ');
  return added;
}

document.getElementById('s-parse-prompt').addEventListener('click', async () => {
  const text = document.getElementById('s-prompt-import').value.trim();
  const resultEl = document.getElementById('s-parse-result');
  if (!text) { resultEl.textContent = ''; return; }
  resultEl.textContent = '파싱 중…';
  const res = await fetch('/parse-prompt', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ text }) });
  const data = await res.json();

  const artistsAdded = mergeLines(document.getElementById('s-artist-tags'), data.artists.map(a => a.tag));
  const qualityAdded = mergeCommaList(document.getElementById('s-quality-prompt'), data.qualities.map(q => q.tag));
  const situationAdded = mergeCommaList(document.getElementById('s-base-prompt'), data.ignored.map(i => i.tag));
  for (const a of data.artists) pendingInitialWeights[a.tag] = a.weight; // BO's first duel starts from these, not a blind 1.0

  const note = data.wiki_available ? '' : ' (danbooru wiki 없음 — artist: / by: 명시 태그만 인식됨)';
  const parts = [];
  if (data.artists.length) parts.push(`작가 ${data.artists.length}개(+${artistsAdded}): ${data.artists.map(a => a.tag).join(', ')}`);
  if (data.qualities.length) parts.push(`퀄리티 ${data.qualities.length}개(+${qualityAdded})`);
  if (data.ignored.length) parts.push(`상황/기타 ${data.ignored.length}개(+${situationAdded})`);
  resultEl.textContent = (parts.length ? parts.join(' · ') : '인식된 태그가 없습니다.') + note;
  toast('artist tags/quality/base prompt에 자동 반영됨');
});

// ---------- init ----------
loadSettings();
pollDuel();
