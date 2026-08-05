/* Песочница тестирования промптов — логика интерфейса.
   Без сборки и зависимостей: файл открывается и правится как есть. */

'use strict';

const state = {
  config: {},
  profiles: [],
  meta: { parts: [], categories: [], severities: [], section_patterns: {} },
  messages: [],          // {role, content} — история для API
  answers: [],           // карточки ответов: {runId, el, bodyEl, text, annotations}
  currentRunId: null,
  lastStart: null,
  lastDone: null,
  selectedRuns: [],
  selectedSuiteLabels: [],
  pendingSelection: null,
  editingIndex: null,
};

/* ---------- мелкие помощники ---------- */

const $ = (id) => document.getElementById(id);
const esc = (text) => String(text ?? '').replace(/[&<>"']/g, (ch) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

function num(value, digits = 0) {
  if (value === null || value === undefined || value === '') return '—';
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return String(value);
  return parsed.toLocaleString('ru-RU', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function money(value) {
  if (value === null || value === undefined) return 'не задана';
  return '$' + Number(value).toFixed(4);
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({ error: 'Некорректный ответ сервера' }));
  if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

async function postJSON(path, body) {
  return api(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
}

let toastTimer = null;
function toast(message, kind = 'ok') {
  const node = $('toast');
  node.textContent = message;
  node.className = 'toast toast-' + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add('hidden'), 3200);
}

function openModal(title, html) {
  $('modal-title').textContent = title;
  $('modal-body').innerHTML = html;
  $('modal').classList.remove('hidden');
}

/* Разбор потока SSE, приходящего в ответ на POST. */
async function streamPost(path, body, handlers) {
  const response = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || `HTTP ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const parts = buffer.split('\n\n');
    buffer = parts.pop();
    for (const part of parts) {
      const eventMatch = part.match(/^event: (.+)$/m);
      const dataMatch = part.match(/^data: ([\s\S]*)$/m);
      if (!eventMatch || !dataMatch) continue;
      let payload;
      try { payload = JSON.parse(dataMatch[1]); } catch { continue; }
      const handler = handlers[eventMatch[1]];
      if (handler) handler(payload);
    }
  }
}

/* ---------- запуск ---------- */

async function init() {
  const savedTheme = localStorage.getItem('sandbox-theme');
  if (savedTheme) document.documentElement.dataset.theme = savedTheme;

  try {
    state.config = await api('/api/config');
  } catch (error) {
    toast('Сервер недоступен: ' + error.message, 'bad');
    return;
  }

  const modeBadge = $('mode-badge');
  if (state.config.mock) {
    modeBadge.textContent = 'MOCK — запросы не уходят в API';
    modeBadge.className = 'badge badge-warn';
  } else {
    modeBadge.textContent = 'Рабочий режим';
    modeBadge.className = 'badge badge-good';
  }
  $('api-badge').textContent = state.config.base_url.replace(/^https?:\/\//, '');

  await Promise.all([loadProfiles(), loadMeta(), loadSuites()]);
  loadModels();
  wireEvents();
}

async function loadProfiles() {
  state.profiles = await api('/api/profiles');
  const options = state.profiles
    .map((profile) => `<option value="${esc(profile.id)}">${esc(profile.name)}</option>`)
    .join('');
  $('profile-select').innerHTML = options;
  $('suite-profile').innerHTML = '<option value="">— из набора —</option>' + options;
  $('runs-filter-profile').innerHTML = '<option value="">Все профили</option>' + options;
  showProfileNote();
}

async function loadMeta() {
  state.meta = await api('/api/annotation-meta');
  $('annot-part').innerHTML = state.meta.parts
    .map((part) => `<option value="${esc(part.id)}">${esc(part.label)}</option>`).join('');
  $('annot-category').innerHTML = state.meta.categories
    .map((cat) => `<option value="${esc(cat.id)}">${esc(cat.label)}</option>`).join('');
  $('annot-severity').innerHTML = state.meta.severities
    .map((sev) => `<option value="${esc(sev.id)}">${esc(sev.label)}</option>`).join('');
}

async function loadModels() {
  try {
    const data = await api('/api/models');
    $('model-list').innerHTML = (data.models || [])
      .map((model) => `<option value="${esc(model)}"></option>`).join('');
  } catch { /* список моделей необязателен */ }
}

function currentProfile() {
  return state.profiles.find((profile) => profile.id === $('profile-select').value);
}

function showProfileNote() {
  const profile = currentProfile();
  if (!profile) { $('profile-note').textContent = ''; return; }
  const files = [...(profile.system_files || []), ...(profile.context_files || [])];
  const parts = [];
  if (profile.description) parts.push(esc(profile.description));
  parts.push(`<span class="mono">${esc(profile.path)}</span> · sha <span class="mono">${esc(profile.source_sha)}</span>`);
  if (files.length) parts.push('файлы: ' + files.map((f) => `<span class="mono">${esc(f)}</span>`).join(', '));
  $('profile-note').innerHTML = parts.join(' · ');
}

function overrides() {
  const result = {};
  const model = $('model-input').value.trim();
  const temperature = $('temp-input').value.trim();
  const seed = $('seed-input').value.trim();
  if (model) result.model = model;
  if (temperature !== '') result.temperature = Number(temperature);
  if (seed !== '') result.seed = Number(seed);
  if ($('logprobs-toggle').checked) result.logprobs = true;
  return result;
}

/* ---------- чат ---------- */

function addUserMessage(text) {
  const node = document.createElement('div');
  node.className = 'msg msg-user';
  node.textContent = text;
  $('messages').appendChild(node);
  scrollChat();
}

function addAnswerCard(profileName) {
  const wrap = document.createElement('div');
  wrap.className = 'msg msg-assistant';
  wrap.innerHTML = `
    <div class="msg-head">
      <span>${esc(profileName)}</span>
      <span class="msg-run mono dim"></span>
    </div>
    <div class="msg-body streaming"></div>
    <div class="msg-footer"></div>`;
  $('messages').appendChild(wrap);
  scrollChat();
  return {
    wrap,
    head: wrap.querySelector('.msg-run'),
    body: wrap.querySelector('.msg-body'),
    footer: wrap.querySelector('.msg-footer'),
  };
}

function scrollChat() {
  const box = $('messages');
  box.scrollTop = box.scrollHeight;
}

async function send() {
  const input = $('input');
  const text = input.value.trim();
  if (!text) return;
  const profile = currentProfile();
  if (!profile) { toast('Не выбран профиль', 'bad'); return; }

  const emptyState = document.querySelector('.empty-state');
  if (emptyState) emptyState.remove();

  input.value = '';
  addUserMessage(text);
  $('send-btn').disabled = true;

  const card = addAnswerCard(profile.name);
  const history = $('history-toggle').checked ? state.messages.slice() : [];
  let buffer = '';

  try {
    await streamPost('/api/chat', {
      profile: profile.id,
      message: text,
      history,
      overrides: overrides(),
    }, {
      start: (payload) => {
        state.currentRunId = payload.run_id;
        state.lastStart = payload;
        card.head.textContent = payload.run_id;
        $('run-id-label').textContent = payload.run_id;
        renderLogRail(payload, null);
      },
      delta: (payload) => {
        buffer += payload.text;
        card.body.textContent = buffer;
        scrollChat();
      },
      done: (payload) => {
        state.lastDone = payload;
        card.body.classList.remove('streaming');
        if (payload.response.error) {
          card.body.textContent = '';
          const error = document.createElement('div');
          error.className = 'msg-error';
          error.textContent = 'Ошибка запроса: ' + payload.response.error;
          card.wrap.appendChild(error);
        } else {
          buffer = payload.response.text || buffer;
          card.body.textContent = buffer;
          state.messages.push({ role: 'user', content: text });
          state.messages.push({ role: 'assistant', content: buffer });
        }
        registerAnswer(payload.run_id, card, buffer);
        renderLogRail(state.lastStart, payload);
        renderMarksRail();
      },
    });
  } catch (error) {
    card.body.classList.remove('streaming');
    card.body.textContent = '';
    const node = document.createElement('div');
    node.className = 'msg-error';
    node.textContent = 'Сбой: ' + error.message;
    card.wrap.appendChild(node);
  } finally {
    $('send-btn').disabled = false;
  }
}

function registerAnswer(runId, card, text) {
  const answer = { runId, card, text, annotations: [] };
  state.answers.push(answer);
  card.wrap.dataset.runId = runId;
  card.body.dataset.runId = runId;
  renderAnswerFooter(answer);
  return answer;
}

function answerByRun(runId) {
  return state.answers.find((item) => item.runId === runId);
}

function renderAnswerFooter(answer) {
  const done = state.lastDone && state.lastDone.run_id === answer.runId ? state.lastDone : null;
  const chips = [];
  if (done) {
    const summary = done.checks_summary || {};
    const clean = !(done.deviations || []).length;
    chips.push(`<span class="badge ${clean ? 'badge-good' : 'badge-warn'}">${clean ? '✓ чистый прогон' : '△ отклонений: ' + done.deviations.length}</span>`);
    if (summary.total) {
      chips.push(`<span class="badge ${summary.ok ? 'badge-good' : 'badge-critical'}">проверки ${summary.passed}/${summary.total}</span>`);
    }
    const usage = done.response.usage || {};
    chips.push(`<span class="badge badge-muted">${num(usage.prompt_tokens)} + ${num(usage.completion_tokens)} ток.</span>`);
    chips.push(`<span class="badge badge-muted">${done.cost && done.cost.known ? money(done.cost.total) : 'цена не задана'}</span>`);
    chips.push(`<span class="badge badge-muted">${num(done.response.latency_ms)} мс</span>`);
  }
  const count = answer.annotations.length;
  chips.push(`<span class="badge ${count ? 'badge-critical' : 'badge-muted'}" data-marks="${esc(answer.runId)}">замечаний: ${count}</span>`);
  answer.card.footer.innerHTML = chips.join(' ') +
    ` <button class="btn btn-sm" data-focus-run="${esc(answer.runId)}">Разметка</button>`;
}

/* ---------- разметка: выделение и форма ---------- */

function offsetsWithin(container, range) {
  const pre = document.createRange();
  pre.selectNodeContents(container);
  pre.setEnd(range.startContainer, range.startOffset);
  const start = pre.toString().length;
  return { start, end: start + range.toString().length };
}

function guessPart(text, start) {
  const patterns = state.meta.section_patterns || {};
  const before = (text || '').slice(0, start).toLowerCase();
  let best = null;
  for (const [partId, markers] of Object.entries(patterns)) {
    for (const marker of markers) {
      const index = before.lastIndexOf(String(marker).toLowerCase());
      if (index >= 0 && (best === null || index > best.index)) best = { index, partId };
    }
  }
  return best ? best.partId : (state.meta.parts[0] ? state.meta.parts[0].id : 'other');
}

function handleSelection() {
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return;
  const range = selection.getRangeAt(0);
  const body = range.commonAncestorContainer.parentElement
    ? range.commonAncestorContainer.parentElement.closest('.msg-body[data-run-id]')
    : null;
  if (!body) return;
  const quote = selection.toString().trim();
  if (quote.length < 2) return;

  const answer = answerByRun(body.dataset.runId);
  if (!answer) return;

  const { start, end } = offsetsWithin(body, range);
  state.pendingSelection = { runId: answer.runId, quote, start, end };
  state.editingIndex = null;

  $('annot-quote').textContent = quote.length > 300 ? quote.slice(0, 300) + '…' : quote;
  $('annot-comment').value = '';
  $('annot-part').value = guessPart(answer.text, start);
  if (state.meta.severities[1]) $('annot-severity').value = state.meta.severities[1].id;

  const rect = range.getBoundingClientRect();
  showPopup(rect);
}

function showPopup(rect) {
  const pop = $('annot-pop');
  pop.classList.remove('hidden');
  const width = pop.offsetWidth || 380;
  const height = pop.offsetHeight || 320;
  let left = rect.left + window.scrollX;
  let top = rect.bottom + window.scrollY + 8;
  left = Math.min(left, window.scrollX + window.innerWidth - width - 16);
  left = Math.max(left, window.scrollX + 8);
  if (rect.bottom + height + 24 > window.innerHeight) {
    top = rect.top + window.scrollY - height - 8;
  }
  pop.style.left = left + 'px';
  pop.style.top = Math.max(8, top) + 'px';
  $('annot-comment').focus();
}

function hidePopup() {
  $('annot-pop').classList.add('hidden');
  state.pendingSelection = null;
  state.editingIndex = null;
}

async function saveAnnotation() {
  const pending = state.pendingSelection;
  if (!pending) return;
  const answer = answerByRun(pending.runId);
  if (!answer) return;

  const comment = $('annot-comment').value.trim();
  if (!comment) { toast('Опишите, что именно не так', 'bad'); return; }

  const annotation = {
    part: $('annot-part').value,
    category: $('annot-category').value,
    severity: $('annot-severity').value,
    quote: pending.quote,
    start: pending.start,
    end: pending.end,
    comment,
  };

  const list = answer.annotations.slice();
  if (state.editingIndex !== null) list[state.editingIndex] = annotation;
  else list.push(annotation);
  list.sort((a, b) => (a.start ?? 0) - (b.start ?? 0));

  try {
    const data = await postJSON(`/api/run/${answer.runId}/annotations`, { annotations: list });
    answer.annotations = data.annotations;
    hidePopup();
    renderHighlights(answer);
    renderAnswerFooter(answer);
    renderMarksRail(answer.runId);
    toast('Замечание сохранено — в логе и в annotations.jsonl');
  } catch (error) {
    toast('Не сохранилось: ' + error.message, 'bad');
  }
}

async function deleteAnnotation(runId, index) {
  const answer = answerByRun(runId);
  if (!answer) return;
  const list = answer.annotations.slice();
  list.splice(index, 1);
  const data = await postJSON(`/api/run/${runId}/annotations`, { annotations: list });
  answer.annotations = data.annotations;
  renderHighlights(answer);
  renderAnswerFooter(answer);
  renderMarksRail(runId);
}

function renderHighlights(answer) {
  const text = answer.text || '';
  const marks = (answer.annotations || [])
    .filter((item) => Number.isInteger(item.start) && Number.isInteger(item.end) && item.end > item.start)
    .sort((a, b) => a.start - b.start);

  let html = '';
  let cursor = 0;
  marks.forEach((mark, index) => {
    if (mark.start < cursor) return; // пересечения не подсвечиваем повторно
    html += esc(text.slice(cursor, mark.start));
    html += `<mark class="ann ann-${esc(mark.severity)}" data-run="${esc(answer.runId)}" data-index="${index}" title="${esc(mark.comment)}">`
      + esc(text.slice(mark.start, mark.end))
      + `<sup>${mark.n || index + 1}</sup></mark>`;
    cursor = mark.end;
  });
  html += esc(text.slice(cursor));
  answer.card.body.innerHTML = html;
}

/* ---------- правая колонка: разметка ---------- */

function partLabel(id) {
  const found = (state.meta.parts || []).find((part) => part.id === id);
  return found ? found.label : id;
}
function categoryLabel(id) {
  const found = (state.meta.categories || []).find((cat) => cat.id === id);
  return found ? found.label : (id || 'без категории');
}
function severityClass(id) {
  if (id === 'blocker') return 'badge-critical';
  if (id === 'major') return 'badge-warn';
  return 'badge-muted';
}

function renderMarksRail(runId) {
  const answer = runId ? answerByRun(runId) : state.answers[state.answers.length - 1];
  const box = $('rail-marks');
  if (!answer) {
    box.innerHTML = '<p class="dim">Выделите фрагмент в ответе модели, чтобы поставить замечание.</p>';
    return;
  }
  if (!answer.annotations.length) {
    box.innerHTML = `<p class="dim">Замечаний к прогону <span class="mono">${esc(answer.runId)}</span> пока нет.
      Выделите фрагмент прямо в тексте ответа.</p>`;
    return;
  }

  const grouped = {};
  answer.annotations.forEach((item, index) => {
    (grouped[item.part] = grouped[item.part] || []).push({ item, index });
  });

  let html = '';
  for (const [partId, entries] of Object.entries(grouped)) {
    html += `<div class="section-label">${esc(partLabel(partId))} — ${entries.length}</div>`;
    for (const { item, index } of entries) {
      const evidence = item.evidence || {};
      const facts = evidence.facts || [];
      const confidence = evidence.confidence || {};
      html += `
      <div class="card">
        <div class="card-title">
          <span>${item.n}. ${esc(categoryLabel(item.category))}</span>
          <span class="badge ${severityClass(item.severity)}">${esc(item.severity)}</span>
        </div>
        <div class="card-body">
          <blockquote class="ann-quote">${esc(item.quote)}</blockquote>
          <p class="ann-comment">${esc(item.comment)}</p>
          ${facts.length ? `<div class="section-label">Факты о входе</div>
            <ul class="facts">${facts.map((fact) => `<li>${esc(fact)}</li>`).join('')}</ul>` : ''}
          ${confidence.available && confidence.span ? `
            <div class="conf-row">
              <span class="dim">уверенность на фрагменте</span>
              <span class="mono">${(confidence.mean_probability * 100).toFixed(0)}%</span>
              <span class="dim">по ответу</span>
              <span class="mono">${(confidence.answer_mean_probability * 100).toFixed(0)}%</span>
            </div>` : ''}
          ${(evidence.terms_missing_from_prompt || []).length ? `
            <div class="ann-missing">Нет в промпте: ${evidence.terms_missing_from_prompt.slice(0, 8).map((t) => `<code>${esc(t)}</code>`).join(' ')}</div>` : ''}
          <div class="ann-actions">
            <button class="btn btn-sm" data-probe="stability" data-run="${esc(answer.runId)}" data-index="${index}">Стабильность ×5</button>
            <button class="btn btn-sm" data-probe="ablation" data-run="${esc(answer.runId)}" data-index="${index}">Абляция</button>
            <button class="btn btn-sm btn-ghost" data-del-ann="${esc(answer.runId)}" data-index="${index}">Удалить</button>
          </div>
        </div>
      </div>`;
    }
  }
  box.innerHTML = html;
}

/* ---------- правая колонка: лог прогона ---------- */

function renderLogRail(start, done) {
  if (!start) return;
  const prompt = start.prompt || {};
  const deviations = (done && done.deviations) || prompt.deviations || [];
  const clean = !deviations.length;

  let html = `
    <div class="purity ${clean ? 'purity-clean' : 'purity-dirty'}">
      <span class="purity-mark">${clean ? '✓' : '△'}</span>
      <span class="purity-text">
        <strong>${clean ? 'Чистый прогон' : 'Отклонений от чистого вызова: ' + deviations.length}</strong>
        <span>${clean ? 'запрос эквивалентен прямому вызову API' : 'сравнение с платформой требует поправки'}</span>
      </span>
    </div>`;

  if (deviations.length) {
    html += '<div class="card"><div class="card-title">Что добавила песочница</div>';
    for (const deviation of deviations) {
      const severity = deviation.severity === 'high' ? 'sev-high' : deviation.severity === 'warn' ? 'sev-warn' : 'sev-info';
      html += `<div class="dev-item ${severity}">
        <span class="dev-mark">${deviation.severity === 'high' ? '●' : deviation.severity === 'warn' ? '◐' : '○'}</span>
        <span><span class="dev-code">${esc(deviation.code)}</span><br>${esc(deviation.detail)}</span>
      </div>`;
    }
    html += '</div>';
  }

  if (done) {
    const usage = done.response.usage || {};
    const details = usage.completion_tokens_details || {};
    html += `<div class="card"><div class="card-title">Показания</div><div class="metrics">
      <div class="metric"><div class="metric-label">Промпт</div><div class="metric-value">${num(usage.prompt_tokens)}</div><div class="metric-sub">токенов</div></div>
      <div class="metric"><div class="metric-label">Ответ</div><div class="metric-value">${num(usage.completion_tokens)}</div><div class="metric-sub">${details.reasoning_tokens ? num(details.reasoning_tokens) + ' reasoning' : 'токенов'}</div></div>
      <div class="metric"><div class="metric-label">Стоимость</div><div class="metric-value">${done.cost && done.cost.known ? money(done.cost.total) : '—'}</div><div class="metric-sub">${done.cost && done.cost.known ? 'USD' : 'цена не задана'}</div></div>
      <div class="metric"><div class="metric-label">Задержка</div><div class="metric-value">${num(done.response.latency_ms)}</div><div class="metric-sub">TTFB ${num(done.response.ttfb_ms)} мс</div></div>
    </div></div>`;

    if (done.response.finish_reason === 'length') {
      html += `<div class="verdict verdict-bad">Ответ оборван лимитом токенов (finish_reason=length).
        Неполнота ответа объясняется этим, а не промптом.</div>`;
    }
  }

  const blocks = prompt.blocks || [];
  if (blocks.length) {
    const total = Math.max(1, prompt.system_tokens || 1);
    html += `<div class="card"><div class="card-title"><span>Состав промпта</span>
      <span class="mono">${num(prompt.system_tokens)} ток.</span></div>`;
    for (const block of blocks) {
      const share = 100 * (block.tokens || 0) / total;
      html += `<div class="comp-row">
        <div class="comp-top">
          <span class="comp-src">${esc(block.source)}${block.missing ? ' ⚠ не прочитан' : ''}${block.truncated ? ' ✂ обрезан' : ''}</span>
          <span class="comp-num">${num(block.tokens)} · ${share.toFixed(0)}%</span>
        </div>
        <div class="meter"><div class="meter-fill" style="width:${Math.max(1, share).toFixed(1)}%"></div></div>
        <div class="comp-meta">sha ${esc(block.sha256 || '—')}${block.mtime ? ' · ' + esc(block.mtime.slice(0, 16)) : ''}</div>
      </div>`;
    }
    html += `<div class="comp-row"><div class="comp-meta">оценка токенов: ${esc(prompt.estimation_method || '—')}</div></div></div>`;
  }

  if (done && (done.checks || []).length) {
    const summary = done.checks_summary || {};
    html += `<div class="card"><div class="card-title"><span>Автопроверки</span>
      <span class="badge ${summary.ok ? 'badge-good' : 'badge-critical'}">${summary.passed}/${summary.total}</span></div>`;
    for (const check of done.checks) {
      const cls = check.passed ? 'check-pass' : (check.severity === 'warn' ? 'check-warn' : 'check-fail');
      html += `<div class="check-item ${cls}">
        <span class="check-mark">${check.passed ? '✓' : (check.severity === 'warn' ? '△' : '✕')}</span>
        <span>${esc(check.kind)}${check.arg ? ' <code>' + esc(check.arg) + '</code>' : ''}
          ${check.detail ? '<br><span class="dim">' + esc(check.detail) + '</span>' : ''}</span>
      </div>`;
    }
    html += '</div>';
  }

  const git = start.git || {};
  html += `<div class="card"><div class="card-title">Версия входа</div><div class="card-body">
    <dl class="kv">
      <dt>ветка</dt><dd>${esc(git.branch || '—')}</dd>
      <dt>коммит</dt><dd>${esc(git.commit || '—')}</dd>
      <dt>промпт sha</dt><dd>${esc((prompt.system_sha256 || '').slice(0, 16))}</dd>
      <dt>модель</dt><dd>${esc((start.request || {}).model || '—')}</dd>
      <dt>seed</dt><dd>${(start.request || {}).seed ?? 'не задан'}</dd>
    </dl>
    ${(git.dirty_watched || []).length ? `<p class="warn-line">Изменены незакоммиченные файлы промпта: ${git.dirty_watched.map(esc).join(', ')}</p>` : ''}
  </div></div>`;

  $('rail-log').innerHTML = html;
}

/* ---------- пробы ---------- */

async function runProbe(kind, runId, index) {
  const title = kind === 'stability' ? 'Проба на стабильность' : 'Проба абляцией';
  openModal(title, '<p class="dim">Идут повторные прогоны, это может занять минуту…</p>');
  try {
    const data = await postJSON(`/api/probe/${kind}`, {
      run_id: runId,
      annotation_index: index,
      repeats: 5,
    });
    openModal(title, kind === 'stability' ? renderStability(data) : renderAblation(data));
  } catch (error) {
    openModal(title, `<div class="verdict verdict-bad">Не удалось: ${esc(error.message)}</div>`);
  }
}

function renderStability(data) {
  const rows = data.repeats.map((repeat, index) => `
    <tr class="${repeat.reproduced ? 'row-regressed' : 'row-improved'}">
      <td class="num">${index + 1}</td>
      <td>${repeat.reproduced ? 'воспроизвёлся' : 'не воспроизвёлся'}</td>
      <td class="num">${repeat.terms.share === null ? '—' : (repeat.terms.share * 100).toFixed(0) + '%'}</td>
      <td class="num">${repeat.similarity_to_original.toFixed(2)}</td>
      <td class="num">${num(repeat.checks_failed)}</td>
      <td class="mono">${esc(repeat.run_id)}</td>
    </tr>`).join('');

  return `
    <div class="verdict ${data.reproduced_count === data.repeats_total ? 'verdict-bad' : data.reproduced_count === 0 ? 'verdict-good' : 'verdict-neutral'}">
      ${esc(data.verdict)}
    </div>
    ${data.quote ? `<blockquote class="ann-quote">${esc(data.quote)}</blockquote>` : ''}
    <p class="dim">Проверяемые термины: ${(data.terms || []).map((t) => `<code>${esc(t)}</code>`).join(' ') || '—'}.
      Seed снят намеренно — проба меряет разброс.</p>
    <table class="grid"><thead><tr><th>#</th><th>Фрагмент</th><th>Терминов</th><th>Схожесть</th><th>Провалов</th><th>Прогон</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function renderAblation(data) {
  const rows = data.variants.map((variant) => `
    <tr class="${variant.dropped === null ? 'row-same' : (variant.reproduced ? 'row-regressed' : 'row-improved')}">
      <td>${esc(variant.label)}</td>
      <td>${variant.reproduced ? 'ошибка осталась' : 'ошибка исчезла'}</td>
      <td class="num">${variant.terms.share === null ? '—' : (variant.terms.share * 100).toFixed(0) + '%'}</td>
      <td class="num">${num(variant.system_tokens)}</td>
      <td class="num">${num(variant.checks_failed)}</td>
      <td class="mono">${esc(variant.run_id)}</td>
    </tr>`).join('');

  return `
    <div class="verdict ${data.culprits.length ? 'verdict-good' : 'verdict-neutral'}">${esc(data.verdict)}</div>
    ${data.quote ? `<blockquote class="ann-quote">${esc(data.quote)}</blockquote>` : ''}
    <table class="grid"><thead><tr><th>Вариант</th><th>Результат</th><th>Терминов</th><th>Токенов промпта</th><th>Провалов</th><th>Прогон</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

/* ---------- вкладка «Замечания» ---------- */

async function loadFindings() {
  const data = await api('/api/annotations');
  if (!data.total) {
    $('findings-body').innerHTML = '<p class="dim">Замечаний пока нет. Разметьте первый ответ во вкладке «Чат и разметка».</p>';
    return;
  }
  const maxCategory = Math.max(...data.by_category.map((item) => item.count), 1);

  const categories = data.by_category.map((item) => `
    <div class="comp-row">
      <div class="comp-top"><span>${esc(item.label)}</span><span class="comp-num">${item.count}</span></div>
      <div class="meter"><div class="meter-fill" style="width:${(100 * item.count / maxCategory).toFixed(1)}%"></div></div>
    </div>`).join('');

  const parts = data.by_part.map((item) =>
    `<span class="badge badge-muted">${esc(item.label)}: ${item.count}</span>`).join(' ');

  const entries = data.entries.slice(0, 80).map((entry) => `
    <tr>
      <td class="mono">${esc((entry.run_ts || '').slice(0, 16))}</td>
      <td>${esc(partLabel(entry.part))}</td>
      <td>${esc(categoryLabel(entry.category))}</td>
      <td><span class="badge ${severityClass(entry.severity)}">${esc(entry.severity)}</span></td>
      <td class="clip" title="${esc(entry.quote)}">${esc(entry.quote)}</td>
      <td class="clip" title="${esc(entry.comment)}">${esc(entry.comment)}</td>
      <td class="mono">${esc(entry.profile || '')}</td>
      <td class="mono">${esc(entry.run_id)}</td>
    </tr>`).join('');

  $('findings-body').innerHTML = `
    <div class="metrics" style="margin-bottom:14px">
      <div class="metric"><div class="metric-label">Замечаний</div><div class="metric-value">${data.total}</div></div>
      <div class="metric"><div class="metric-label">Размечено прогонов</div><div class="metric-value">${data.runs_annotated}</div></div>
    </div>
    <div class="chip-row">${parts}</div>
    <div class="diff-grid">
      <div class="card"><div class="card-title">Что повторяется чаще всего</div>${categories}</div>
      <div class="card"><div class="card-title">Файлы для разбора</div><div class="card-body">
        <dl class="kv">
          <dt>поток</dt><dd>${esc(data.stream_path)}</dd>
          <dt>сводка</dt><dd>${esc(data.digest_path)}</dd>
        </dl>
        <p class="dim">Обе дорожки читаются Claude Code напрямую: <code>annotations.jsonl</code> —
          построчно для анализа, <code>ANNOTATIONS.md</code> — для чтения.</p>
      </div></div>
    </div>
    <div class="section-label">Последние замечания</div>
    <div class="table-wrap" style="padding:0">
      <table class="grid"><thead><tr><th>Когда</th><th>Часть</th><th>Категория</th><th>Важность</th><th>Цитата</th><th>Комментарий</th><th>Профиль</th><th>Прогон</th></tr></thead>
      <tbody>${entries}</tbody></table>
    </div>`;
}

/* ---------- вкладка «Прогоны» ---------- */

async function loadRuns() {
  const profile = $('runs-filter-profile').value;
  const errors = $('runs-filter-errors').checked ? '1' : '';
  const runs = await api(`/api/runs?limit=200&profile=${encodeURIComponent(profile)}&errors=${errors}`);
  const body = document.querySelector('#runs-table tbody');
  body.innerHTML = runs.map((run) => `
    <tr class="row-link" data-run="${esc(run.id)}">
      <td><input type="checkbox" data-pick="${esc(run.id)}"></td>
      <td class="mono">${esc(run.ts.slice(0, 16).replace('T', ' '))}</td>
      <td>${esc(run.profile_name || run.profile)}</td>
      <td class="mono">${esc(run.model || '')}</td>
      <td class="clip" title="${esc(run.question)}">${esc(run.question)}</td>
      <td class="mono">${esc(run.system_sha || '')}</td>
      <td class="num">${num(run.prompt_tokens)}</td>
      <td class="num">${run.cost === null || run.cost === undefined ? '—' : money(run.cost)}</td>
      <td class="num">${num(run.latency_ms)}</td>
      <td>${run.checks_failed ? `<span class="badge badge-critical">${run.checks_failed} провал.</span>` : '<span class="badge badge-good">ок</span>'}</td>
      <td class="num">${run.annotations_count || ''}</td>
      <td>${run.clean ? '<span class="badge badge-good">чистый</span>' : `<span class="badge badge-warn">${run.deviations}</span>`}</td>
    </tr>`).join('');

  body.querySelectorAll('[data-pick]').forEach((box) => {
    box.addEventListener('change', (event) => {
      event.stopPropagation();
      const id = box.dataset.pick;
      if (box.checked) state.selectedRuns.push(id);
      else state.selectedRuns = state.selectedRuns.filter((item) => item !== id);
      $('runs-compare').disabled = state.selectedRuns.length !== 2;
      $('runs-compare').textContent = `Сравнить выбранные (${state.selectedRuns.length})`;
    });
  });

  body.querySelectorAll('tr[data-run]').forEach((row) => {
    row.addEventListener('click', () => showRunDetail(row.dataset.run));
  });
}

async function showRunDetail(runId) {
  const record = await api('/api/run/' + runId);
  const response = record.response || {};
  const annotations = record.annotations || [];
  $('run-detail').innerHTML = `
    <div class="section-label">Прогон ${esc(runId)}</div>
    <div class="diff-grid">
      <div>
        <div class="card"><div class="card-title">Вопрос</div><div class="card-body">${esc(record.input.user_message)}</div></div>
        <div class="card"><div class="card-title">Ответ</div><div class="card-body" style="font-family:var(--font-read);font-size:15px;white-space:pre-wrap">${esc(response.text || response.error || '')}</div></div>
      </div>
      <div>
        <div class="card"><div class="card-title">Замечания (${annotations.length})</div>
          ${annotations.length ? annotations.map((item) => `
            <div class="check-item ${item.severity === 'blocker' ? 'check-fail' : 'check-warn'}">
              <span class="check-mark">${item.n}</span>
              <span><strong>${esc(categoryLabel(item.category))}</strong> · ${esc(partLabel(item.part))}<br>
                <span class="dim">${esc(item.quote.slice(0, 160))}</span><br>${esc(item.comment)}</span>
            </div>`).join('') : '<div class="card-body dim">Не размечен</div>'}
        </div>
        <div class="card"><div class="card-title">Системный промпт</div>
          <div class="card-body"><pre class="code">${esc((record.prompt.system_prompt || '').slice(0, 4000))}</pre></div>
        </div>
      </div>
    </div>`;
  $('run-detail').scrollIntoView({ behavior: 'smooth', block: 'start' });
}

/* ---------- сравнение ---------- */

function renderDiffText(diff) {
  return esc(diff).split('\n').map((line) => {
    if (line.startsWith('+')) return `<span class="add">${line}</span>`;
    if (line.startsWith('-')) return `<span class="del">${line}</span>`;
    if (line.startsWith('@@')) return `<span class="hunk">${line}</span>`;
    return line;
  }).join('\n');
}

async function compareRuns(a, b) {
  const data = await api(`/api/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  const diff = data.diff;
  const verdictClass = diff.input.identical ? 'verdict-neutral'
    : (diff.metrics.checks_failed_after < diff.metrics.checks_failed_before ? 'verdict-good' : 'verdict-bad');

  const composition = diff.input.composition;
  const wordDiff = diff.output.word_diff.map((piece) => {
    if (piece.op === 'insert') return `<ins>${esc(piece.text)}</ins>`;
    if (piece.op === 'delete') return `<del>${esc(piece.text)}</del>`;
    return esc(piece.text);
  }).join(' ');

  $('compare-result').innerHTML = `
    <div class="verdict ${verdictClass}">${esc(diff.verdict)}</div>
    <div class="metrics" style="margin-bottom:14px">
      <div class="metric"><div class="metric-label">Схожесть ответов</div><div class="metric-value">${(diff.output.similarity * 100).toFixed(0)}%</div></div>
      <div class="metric"><div class="metric-label">Провалов проверок</div><div class="metric-value">${num(diff.metrics.checks_failed_before)} → ${num(diff.metrics.checks_failed_after)}</div></div>
      <div class="metric"><div class="metric-label">Токенов промпта</div><div class="metric-value">${num(diff.metrics.prompt_tokens_before)} → ${num(diff.metrics.prompt_tokens_after)}</div></div>
      <div class="metric"><div class="metric-label">Длина ответа</div><div class="metric-value">${num(diff.output.len_before)} → ${num(diff.output.len_after)}</div></div>
    </div>
    <div class="section-label">Что изменилось на входе</div>
    <div class="card"><div class="card-body">
      ${composition.added.length ? `<p>Добавлены файлы: ${composition.added.map((f) => `<code>${esc(f)}</code>`).join(', ')}</p>` : ''}
      ${composition.removed.length ? `<p>Убраны файлы: ${composition.removed.map((f) => `<code>${esc(f)}</code>`).join(', ')}</p>` : ''}
      ${composition.changed.length ? `<p>Изменено содержимое: ${composition.changed.map((c) => `<code>${esc(c.source)}</code> (${num(c.tokens_before)}→${num(c.tokens_after)} ток.)`).join(', ')}</p>` : ''}
      ${diff.input.params.length ? `<p>Параметры: ${diff.input.params.map((p) => `<code>${esc(p.param)}</code> ${esc(String(p.before))}→${esc(String(p.after))}`).join(', ')}</p>` : ''}
      ${diff.input.identical ? '<p class="dim">Вход идентичен.</p>' : ''}
    </div></div>
    ${diff.input.system_prompt_diff ? `<div class="section-label">Диф системного промпта</div>
      <pre class="diff">${renderDiffText(diff.input.system_prompt_diff)}</pre>` : ''}
    <div class="section-label">Что изменилось в ответе</div>
    <div class="worddiff">${wordDiff}</div>`;
  switchTab('compare');
}

/* ---------- наборы тестов ---------- */

async function loadSuites() {
  const suites = await api('/api/suites');
  $('suite-select').innerHTML = suites
    .map((suite) => `<option value="${esc(suite.id)}">${esc(suite.name)} (${suite.items.length})</option>`).join('');
  if (suites.length) loadSuiteResults();
}

async function loadSuiteResults() {
  const suiteId = $('suite-select').value;
  if (!suiteId) return;
  const results = await api('/api/suite/results/' + encodeURIComponent(suiteId));
  const body = document.querySelector('#suite-results-table tbody');
  state.selectedSuiteLabels = [];
  body.innerHTML = results.map((result) => `
    <tr>
      <td><input type="checkbox" data-label="${esc(result.label)}"></td>
      <td><strong>${esc(result.label)}</strong></td>
      <td class="mono">${esc((result.ts || '').slice(0, 16).replace('T', ' '))}</td>
      <td>${esc(result.profile)}</td>
      <td class="mono">${esc(result.model)}</td>
      <td class="mono">${esc(result.system_sha)}</td>
      <td class="num">${result.summary.items_ok}/${result.summary.items}</td>
      <td class="num">${result.summary.checks_failed_total}</td>
      <td class="num">${result.summary.judge_avg ?? '—'}</td>
      <td class="num">${result.summary.cost_total === null ? '—' : money(result.summary.cost_total)}</td>
    </tr>`).join('');

  body.querySelectorAll('[data-label]').forEach((box) => {
    box.addEventListener('change', () => {
      const label = box.dataset.label;
      if (box.checked) state.selectedSuiteLabels.push(label);
      else state.selectedSuiteLabels = state.selectedSuiteLabels.filter((item) => item !== label);
      $('suite-compare-btn').disabled = state.selectedSuiteLabels.length !== 2;
      $('suite-compare-btn').textContent = `Сравнить выбранные (${state.selectedSuiteLabels.length})`;
    });
  });
}

async function runSuite() {
  const suiteId = $('suite-select').value;
  const label = $('suite-label').value.trim();
  if (!label) { toast('Задайте метку прогона — по ней потом сравнивать', 'bad'); return; }
  $('suite-run').disabled = true;
  $('suite-progress').textContent = 'Запуск…';

  try {
    await streamPost('/api/suite/run', {
      suite: suiteId,
      profile: $('suite-profile').value,
      label,
      judge: $('suite-judge').checked,
      overrides: overrides(),
    }, {
      progress: (payload) => {
        $('suite-progress').textContent = `${payload.done} / ${payload.total} — ${payload.title}`;
      },
      done: (report) => {
        $('suite-progress').textContent = 'Готово.';
        const summary = report.summary;
        $('suite-info').innerHTML = `
          <div class="verdict ${summary.items_failed ? 'verdict-bad' : 'verdict-good'}">
            Метка <strong>${esc(report.label)}</strong>: пройдено ${summary.items_ok} из ${summary.items},
            провалов проверок ${summary.checks_failed_total}${summary.judge_avg ? `, средний балл судьи ${summary.judge_avg}` : ''}.
          </div>`;
        loadSuiteResults();
      },
      error: (payload) => { toast(payload.message, 'bad'); },
    });
  } catch (error) {
    toast('Сбой прогона: ' + error.message, 'bad');
  } finally {
    $('suite-run').disabled = false;
  }
}

async function compareSuites() {
  const [a, b] = state.selectedSuiteLabels;
  const suiteId = $('suite-select').value;
  const data = await api(`/api/suite/compare?suite=${encodeURIComponent(suiteId)}&a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
  const rows = data.rows.map((row) => {
    const cls = row.status === 'улучшение' ? 'row-improved' : row.status === 'регрессия' ? 'row-regressed' : 'row-same';
    return `<tr class="${cls}">
      <td>${esc(row.title)}</td>
      <td>${esc(row.status)}</td>
      <td class="num">${num(row.checks_failed_before)} → ${num(row.checks_failed_after)}</td>
      <td class="num">${row.judge_before ?? '—'} → ${row.judge_after ?? '—'}</td>
      <td class="num">${row.similarity === undefined ? '—' : (row.similarity * 100).toFixed(0) + '%'}</td>
      <td class="clip">${esc((row.failed_after_list || []).join(', '))}</td>
      <td><button class="btn btn-sm" data-cmp-a="${esc(row.run_before)}" data-cmp-b="${esc(row.run_after)}">диф</button></td>
    </tr>`;
  }).join('');

  $('suite-compare').innerHTML = `
    <div class="verdict ${data.totals.regressed ? 'verdict-bad' : data.totals.improved ? 'verdict-good' : 'verdict-neutral'}">
      <strong>${esc(a)}</strong> → <strong>${esc(b)}</strong>:
      улучшений ${data.totals.improved}, регрессий ${data.totals.regressed}, без изменений ${data.totals.unchanged}.
      ${data.input_changed ? 'Системный промпт между прогонами менялся.' : 'Системный промпт не менялся — разница объясняется недетерминированностью модели.'}
    </div>
    <table class="grid"><thead><tr><th>Пункт</th><th>Статус</th><th>Провалов</th><th>Судья</th><th>Схожесть</th><th>Что провалено сейчас</th><th></th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

/* ---------- вкладки и события ---------- */

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.classList.toggle('tab-active', tab.dataset.tab === name);
  });
  document.querySelectorAll('.tab-panel').forEach((panel) => {
    panel.classList.toggle('tab-panel-active', panel.id === 'tab-' + name);
  });
  if (name === 'runs') loadRuns();
  if (name === 'findings') loadFindings();
}

function wireEvents() {
  document.querySelectorAll('.tab').forEach((tab) => {
    tab.addEventListener('click', () => switchTab(tab.dataset.tab));
  });

  document.querySelectorAll('.seg').forEach((seg) => {
    seg.addEventListener('click', () => {
      document.querySelectorAll('.seg').forEach((other) => other.classList.toggle('seg-active', other === seg));
      const marks = seg.dataset.rail === 'marks';
      $('rail-marks').classList.toggle('hidden', !marks);
      $('rail-log').classList.toggle('hidden', marks);
      $('rail-title').textContent = marks ? 'Замечания к ответу' : 'Лог прогона';
    });
  });

  $('send-btn').addEventListener('click', send);
  $('input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) send();
  });
  $('clear-btn').addEventListener('click', () => {
    state.messages = [];
    state.answers = [];
    $('messages').innerHTML = '<div class="empty-state"><p class="dim">Диалог очищен. История для API сброшена.</p></div>';
    renderMarksRail();
  });
  $('profile-select').addEventListener('change', showProfileNote);
  $('reload-btn').addEventListener('click', async () => { await loadProfiles(); await loadMeta(); toast('Профили перечитаны'); });

  $('preview-btn').addEventListener('click', async () => {
    const profile = currentProfile();
    if (!profile) return;
    try {
      const data = await postJSON('/api/preview', {
        profile: profile.id,
        message: $('input').value || '(пример вопроса)',
        overrides: overrides(),
      });
      renderLogRail({ prompt: data.prompt, request: data.request, git: data.git }, null);
      document.querySelector('.seg[data-rail="log"]').click();
      toast('Состав промпта собран без обращения к API');
    } catch (error) { toast(error.message, 'bad'); }
  });

  $('ab-btn').addEventListener('click', abRun);

  $('theme-toggle').addEventListener('click', () => {
    const current = document.documentElement.dataset.theme;
    const next = current === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = next;
    localStorage.setItem('sandbox-theme', next);
  });

  document.addEventListener('mouseup', (event) => {
    if (event.target.closest('#annot-pop')) return;
    setTimeout(handleSelection, 10);
  });

  $('annot-save').addEventListener('click', saveAnnotation);
  $('annot-cancel').addEventListener('click', hidePopup);
  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') { hidePopup(); $('modal').classList.add('hidden'); }
  });

  $('modal-close').addEventListener('click', () => $('modal').classList.add('hidden'));
  $('modal').addEventListener('click', (event) => {
    if (event.target.id === 'modal') $('modal').classList.add('hidden');
  });

  document.addEventListener('click', (event) => {
    const probe = event.target.closest('[data-probe]');
    if (probe) {
      runProbe(probe.dataset.probe, probe.dataset.run, Number(probe.dataset.index));
      return;
    }
    const del = event.target.closest('[data-del-ann]');
    if (del) {
      deleteAnnotation(del.dataset.delAnn, Number(del.dataset.index));
      return;
    }
    const focus = event.target.closest('[data-focus-run]');
    if (focus) {
      renderMarksRail(focus.dataset.focusRun);
      document.querySelector('.seg[data-rail="marks"]').click();
      return;
    }
    const mark = event.target.closest('mark.ann');
    if (mark) {
      renderMarksRail(mark.dataset.run);
      document.querySelector('.seg[data-rail="marks"]').click();
      return;
    }
    const cmp = event.target.closest('[data-cmp-a]');
    if (cmp) compareRuns(cmp.dataset.cmpA, cmp.dataset.cmpB);
  });

  $('runs-refresh').addEventListener('click', loadRuns);
  $('runs-filter-profile').addEventListener('change', loadRuns);
  $('runs-filter-errors').addEventListener('change', loadRuns);
  $('runs-compare').addEventListener('click', () => compareRuns(state.selectedRuns[0], state.selectedRuns[1]));

  $('cmp-run').addEventListener('click', () => {
    const a = $('cmp-a').value.trim();
    const b = $('cmp-b').value.trim();
    if (a && b) compareRuns(a, b);
  });

  $('suite-select').addEventListener('change', loadSuiteResults);
  $('suite-run').addEventListener('click', runSuite);
  $('suite-compare-btn').addEventListener('click', compareSuites);

  $('findings-refresh').addEventListener('click', loadFindings);
  $('findings-digest').addEventListener('click', async () => {
    const data = await postJSON('/api/annotations/digest', {});
    toast('Сводка собрана: ' + data.path);
  });
}

/* A/B: один вопрос через несколько профилей сразу. */
async function abRun() {
  const text = $('input').value.trim();
  if (!text) { toast('Введите вопрос', 'bad'); return; }

  const chosen = prompt(
    'Профили через запятую:\n' + state.profiles.map((p) => p.id).join(', '),
    state.profiles.slice(0, 2).map((p) => p.id).join(',')
  );
  if (!chosen) return;
  const ids = chosen.split(',').map((item) => item.trim()).filter(Boolean);

  const emptyState = document.querySelector('.empty-state');
  if (emptyState) emptyState.remove();
  addUserMessage(text);
  $('input').value = '';

  const grid = document.createElement('div');
  grid.className = 'ab-grid';
  $('messages').appendChild(grid);

  await Promise.all(ids.map(async (id) => {
    const profile = state.profiles.find((item) => item.id === id);
    if (!profile) return;
    const cell = document.createElement('div');
    cell.className = 'ab-cell';
    cell.innerHTML = `<div class="msg-head"><span>${esc(profile.name)}</span><span class="msg-run mono dim"></span></div>
      <div class="msg-body streaming"></div><div class="msg-footer"></div>`;
    grid.appendChild(cell);
    const card = {
      wrap: cell,
      head: cell.querySelector('.msg-run'),
      body: cell.querySelector('.msg-body'),
      footer: cell.querySelector('.msg-footer'),
    };
    let buffer = '';
    try {
      await streamPost('/api/chat', { profile: id, message: text, history: [], overrides: overrides() }, {
        start: (payload) => { card.head.textContent = payload.run_id; },
        delta: (payload) => { buffer += payload.text; card.body.textContent = buffer; },
        done: (payload) => {
          card.body.classList.remove('streaming');
          buffer = payload.response.text || buffer;
          card.body.textContent = buffer;
          state.lastDone = payload;
          registerAnswer(payload.run_id, card, buffer);
        },
      });
    } catch (error) {
      card.body.classList.remove('streaming');
      card.body.textContent = 'Сбой: ' + error.message;
    }
  }));
}

init();
