/* Песочница тестирования промптов — логика интерфейса.
   Без сборки и зависимостей: файл открывается и правится как есть.

   Интерфейс держится на одной задаче: прогнать кейс → разметить ошибки по
   фрагментам → увидеть, откуда ошибка взялась → накопить для разбора.
   Всё, что этой задаче не служит, здесь отсутствует намеренно. */

'use strict';

const state = {
  config: {},
  profiles: [],
  meta: { parts: [], categories: [], severities: [], section_patterns: {} },
  caps: {},
  messages: [],   // история диалога для API
  answers: [],    // карточки ответов на экране
  pendingSelection: null,
};

/* ---------- помощники ---------- */

const $ = (id) => document.getElementById(id);
const esc = (text) => String(text ?? '').replace(/[&<>"']/g, (ch) =>
  ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

function num(value) {
  if (value === null || value === undefined || value === '') return '—';
  const parsed = Number(value);
  return Number.isNaN(parsed) ? String(value) : parsed.toLocaleString('ru-RU');
}

async function api(path, options) {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({ error: 'Некорректный ответ сервера' }));
  if (!response.ok || data.error) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

const postJSON = (path, body) => api(path, {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify(body || {}),
});

let toastTimer = null;
function toast(message, kind = 'ok') {
  const node = $('toast');
  node.textContent = message;
  node.className = 'toast toast-' + kind;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => node.classList.add('hidden'), 3600);
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
  for (;;) {
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

  await Promise.all([loadProfiles(), loadMeta()]);
  loadModels();
  wireEvents();
  applyModelCaps();
}

async function loadProfiles() {
  state.profiles = await api('/api/profiles');
  $('profile-select').innerHTML = state.profiles
    .map((profile) => `<option value="${esc(profile.id)}">${esc(profile.name)}</option>`).join('');
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

/* Модель решает, что имеет смысл показывать. Галочка уверенности появляется
   только у моделей, которые действительно отдают logprobs. */
async function applyModelCaps() {
  const profile = currentProfile();
  const model = $('model-input').value.trim() || (profile && profile.model) || state.config.default_model;
  try {
    state.caps = await api('/api/model-caps?model=' + encodeURIComponent(model));
  } catch { return; }
  const supported = !!state.caps.logprobs;
  $('logprobs-holder').classList.toggle('hidden', !supported);
  if (!supported) $('logprobs-toggle').checked = false;
}

const currentProfile = () => state.profiles.find((p) => p.id === $('profile-select').value);

function showProfileNote() {
  const profile = currentProfile();
  if (!profile) { $('profile-note').textContent = ''; return; }
  const files = [...(profile.system_files || []), ...(profile.context_files || [])];
  const bits = [`<span class="mono">${esc(profile.path)}</span> · sha <span class="mono">${esc(profile.source_sha)}</span>`];
  if (files.length) bits.push('файлы: ' + files.map((f) => `<span class="mono">${esc(f)}</span>`).join(', '));

  // Профиль с невставленным промптом — тест впустую. Молчать об этом нельзя.
  const placeholder = (profile.system_text || '').includes('ВСТАВЬТЕ СЮДА');
  const note = $('profile-note');
  note.classList.toggle('profile-note-alert', placeholder);
  note.innerHTML = (placeholder
    ? `<strong>В этом профиле стоит заглушка, а не ваш промпт.</strong> Вставьте текст инструкций
       ассистента в файл <span class="mono">${esc(profile.path)}</span> (ниже строки <span class="mono">---</span>),
       затем нажмите ↻. Пока этого нет, вы тестируете не своего агента. · `
    : '') + bits.join(' · ');
}

function overrides() {
  const result = {};
  const model = $('model-input').value.trim();
  if (model) result.model = model;
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

function dropEmptyState() {
  const node = document.querySelector('.empty-state');
  if (node) node.remove();
}

async function send() {
  const input = $('input');
  const text = input.value.trim();
  if (!text) return;
  const profile = currentProfile();
  if (!profile) { toast('Не выбран профиль', 'bad'); return; }

  dropEmptyState();
  input.value = '';
  addUserMessage(text);
  $('send-btn').disabled = true;

  const card = addAnswerCard(profile.name);
  const history = $('history-toggle').checked ? state.messages.slice() : [];
  let buffer = '';
  let start = null;

  try {
    await streamPost('/api/chat', {
      profile: profile.id,
      message: text,
      history,
      overrides: overrides(),
    }, {
      start: (payload) => {
        start = payload;
        card.head.textContent = payload.run_id;
        $('run-id-label').textContent = payload.run_id;
      },
      delta: (payload) => {
        buffer += payload.text;
        card.body.textContent = buffer;
        scrollChat();
      },
      done: (payload) => {
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
        const answer = registerAnswer(payload.run_id, card, buffer, [], { start, done: payload });
        renderMarksRail(answer.runId);
        renderWhyRail(answer);
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

function registerAnswer(runId, card, text, annotations, meta) {
  const answer = { runId, card, text, annotations: annotations || [], meta: meta || {} };
  state.answers = state.answers.filter((item) => item.runId !== runId);
  state.answers.push(answer);
  card.wrap.dataset.runId = runId;
  card.body.dataset.runId = runId;
  renderAnswerFooter(answer);
  if (answer.annotations.length) renderHighlights(answer);
  return answer;
}

const answerByRun = (runId) => state.answers.find((item) => item.runId === runId);

function renderAnswerFooter(answer) {
  const done = answer.meta.done;
  const chips = [];
  if (done) {
    const clean = !(done.deviations || []).length;
    chips.push(`<span class="badge ${clean ? 'badge-good' : 'badge-warn'}">${clean ? '✓ чистый прогон' : '△ отклонений: ' + done.deviations.length}</span>`);
    const summary = done.checks_summary || {};
    if (summary.total) {
      chips.push(`<span class="badge ${summary.ok ? 'badge-good' : 'badge-critical'}">проверки ${summary.passed}/${summary.total}</span>`);
    }
    if (done.response && done.response.finish_reason === 'length') {
      chips.push('<span class="badge badge-critical">ответ оборван лимитом</span>');
    }
  }
  const count = answer.annotations.length;
  chips.push(`<span class="badge ${count ? 'badge-critical' : 'badge-muted'}">замечаний: ${count}</span>`);
  answer.card.footer.innerHTML = chips.join(' ') +
    ` <button class="btn btn-sm" data-focus-run="${esc(answer.runId)}">Разметка</button>`;
}

/* ---------- разметка ---------- */

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
  const parent = range.commonAncestorContainer.parentElement;
  const body = parent ? parent.closest('.msg-body[data-run-id]') : null;
  if (!body) return;
  const quote = selection.toString().trim();
  if (quote.length < 2) return;

  const answer = answerByRun(body.dataset.runId);
  if (!answer) return;

  const { start, end } = offsetsWithin(body, range);
  state.pendingSelection = { runId: answer.runId, quote, start, end };

  $('annot-quote').textContent = quote.length > 300 ? quote.slice(0, 300) + '…' : quote;
  $('annot-comment').value = '';
  $('annot-part').value = guessPart(answer.text, start);
  if (state.meta.severities[1]) $('annot-severity').value = state.meta.severities[1].id;

  showPopup(range.getBoundingClientRect());
}

function showPopup(rect) {
  const pop = $('annot-pop');
  pop.classList.remove('hidden');
  const width = pop.offsetWidth || 390;
  const height = pop.offsetHeight || 320;
  let left = Math.min(rect.left + window.scrollX, window.scrollX + window.innerWidth - width - 16);
  left = Math.max(left, window.scrollX + 8);
  let top = rect.bottom + window.scrollY + 8;
  if (rect.bottom + height + 24 > window.innerHeight) top = rect.top + window.scrollY - height - 8;
  pop.style.left = left + 'px';
  pop.style.top = Math.max(8, top) + 'px';
  $('annot-comment').focus();
}

function hidePopup() {
  $('annot-pop').classList.add('hidden');
  state.pendingSelection = null;
}

async function saveAnnotation() {
  const pending = state.pendingSelection;
  if (!pending) return;
  const answer = answerByRun(pending.runId);
  if (!answer) return;

  const comment = $('annot-comment').value.trim();
  if (!comment) { toast('Опишите, что именно не так', 'bad'); return; }

  const list = answer.annotations.concat([{
    part: $('annot-part').value,
    category: $('annot-category').value,
    severity: $('annot-severity').value,
    quote: pending.quote,
    start: pending.start,
    end: pending.end,
    comment,
  }]).sort((a, b) => (a.start ?? 0) - (b.start ?? 0));

  try {
    const data = await postJSON(`/api/run/${answer.runId}/annotations`, { annotations: list });
    answer.annotations = data.annotations;
    hidePopup();
    renderHighlights(answer);
    renderAnswerFooter(answer);
    renderMarksRail(answer.runId);
    toast('Замечание сохранено — в логе прогона и в annotations.jsonl');
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
    if (mark.start < cursor) return;  // пересечения не подсвечиваем дважды
    html += esc(text.slice(cursor, mark.start));
    html += `<mark class="ann ann-${esc(mark.severity)}" data-run="${esc(answer.runId)}" data-index="${index}" title="${esc(mark.comment)}">`
      + esc(text.slice(mark.start, mark.end)) + `<sup>${mark.n || index + 1}</sup></mark>`;
    cursor = mark.end;
  });
  html += esc(text.slice(cursor));
  answer.card.body.innerHTML = html;
}

/* ---------- правая колонка: замечания ---------- */

const partLabel = (id) => (state.meta.parts.find((p) => p.id === id) || {}).label || id;
const categoryLabel = (id) => (state.meta.categories.find((c) => c.id === id) || {}).label || (id || 'без категории');
const severityClass = (id) => (id === 'blocker' ? 'badge-critical' : id === 'major' ? 'badge-warn' : 'badge-muted');

function renderMarksRail(runId) {
  const answer = runId ? answerByRun(runId) : state.answers[state.answers.length - 1];
  const box = $('rail-marks');
  if (!answer) {
    box.innerHTML = '<p class="dim">Выделите фрагмент в ответе модели, чтобы поставить замечание.</p>';
    return;
  }
  $('run-id-label').textContent = answer.runId;

  if (!answer.annotations.length) {
    box.innerHTML = '<p class="dim">Замечаний к этому ответу пока нет. Выделите фрагмент прямо в тексте.</p>';
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
        <div class="card-title card-title-plain">
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
          <div class="ann-actions">
            <button class="btn btn-sm" data-probe="stability" data-run="${esc(answer.runId)}" data-index="${index}"
              title="Повторить запрос 5 раз: воспроизводится ошибка или это случайность">Повторить ×5</button>
            <button class="btn btn-sm" data-probe="ablation" data-run="${esc(answer.runId)}" data-index="${index}"
              title="Прогнать без каждого файла промпта: исчезнет ли ошибка">Абляция</button>
            <button class="btn btn-sm btn-ghost" data-del-ann="${esc(answer.runId)}" data-index="${index}">Удалить</button>
          </div>
        </div>
      </div>`;
    }
  }
  box.innerHTML = html;
}

/* ---------- правая колонка: почему так вышло ---------- */

function renderWhyRail(answer) {
  const start = answer.meta.start;
  const done = answer.meta.done;
  if (!start) { $('rail-log').innerHTML = '<p class="dim">Нет данных по этому прогону.</p>'; return; }

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

  if (done && done.response && done.response.finish_reason === 'length') {
    html += `<div class="verdict verdict-bad">Ответ оборван лимитом токенов (finish_reason=length).
      Неполнота объясняется этим, а не промптом.</div>`;
  }

  if (done) {
    const usage = (done.response && done.response.usage) || {};
    const details = usage.completion_tokens_details || {};
    html += `<div class="card"><div class="card-title">Объём</div><div class="metrics">
      <div class="metric"><div class="metric-label">Промпт</div><div class="metric-value">${num(usage.prompt_tokens)}</div><div class="metric-sub">токенов</div></div>
      <div class="metric"><div class="metric-label">Ответ</div><div class="metric-value">${num(usage.completion_tokens)}</div><div class="metric-sub">${details.reasoning_tokens ? num(details.reasoning_tokens) + ' на рассуждение' : 'токенов'}</div></div>
    </div></div>`;
  }

  const blocks = prompt.blocks || [];
  if (blocks.length) {
    const total = Math.max(1, prompt.system_tokens || 1);
    html += `<div class="card"><div class="card-title"><span>Из чего собран промпт</span>
      <span class="mono">${num(prompt.system_tokens)} ток.</span></div>`;
    for (const block of blocks) {
      const share = 100 * (block.tokens || 0) / total;
      html += `<div class="comp-row">
        <div class="comp-top">
          <span class="comp-src">${esc(block.source)}${block.missing ? ' ⚠ не прочитан' : ''}${block.truncated ? ' ✂ обрезан' : ''}</span>
          <span class="comp-num">${num(block.tokens)} · ${share.toFixed(0)}%</span>
        </div>
        <div class="meter"><div class="meter-fill" style="width:${Math.max(1, share).toFixed(1)}%"></div></div>
        <div class="comp-meta">sha ${esc(block.sha256 || '—')}</div>
      </div>`;
    }
    html += '</div>';
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
      <dt>модель</dt><dd>${esc((start.request || {}).model || '—')}</dd>
      <dt>промпт sha</dt><dd>${esc((prompt.system_sha256 || '').slice(0, 16))}</dd>
      <dt>коммит</dt><dd>${esc(git.commit || '—')}</dd>
    </dl>
    ${(git.dirty_watched || []).length ? `<p class="warn-line">Файлы промпта изменены и не закоммичены: ${git.dirty_watched.map(esc).join(', ')}</p>` : ''}
  </div></div>`;

  $('rail-log').innerHTML = html;
}

/* ---------- пробы ---------- */

async function runProbe(kind, runId, index) {
  const title = kind === 'stability' ? 'Повтор ×5: устойчиво или случайность' : 'Абляция: какой файл виноват';
  openModal(title, '<p class="dim">Идут повторные прогоны, это может занять минуту…</p>');
  try {
    const data = await postJSON(`/api/probe/${kind}`, { run_id: runId, annotation_index: index, repeats: 5 });
    openModal(title, kind === 'stability' ? renderStability(data) : renderAblation(data));
  } catch (error) {
    openModal(title, `<div class="verdict verdict-bad">Не удалось: ${esc(error.message)}</div>`);
  }
}

function renderStability(data) {
  const rows = data.repeats.map((repeat, index) => `
    <tr class="${repeat.reproduced ? 'row-regressed' : 'row-improved'}">
      <td class="num">${index + 1}</td>
      <td>${repeat.reproduced ? 'ошибка повторилась' : 'ошибки нет'}</td>
      <td class="num">${repeat.terms.share === null ? '—' : (repeat.terms.share * 100).toFixed(0) + '%'}</td>
      <td class="mono">${esc(repeat.run_id)}</td>
    </tr>`).join('');
  const tone = data.reproduced_count === data.repeats_total ? 'verdict-bad'
    : data.reproduced_count === 0 ? 'verdict-good' : 'verdict-neutral';
  return `
    <div class="verdict ${tone}">${esc(data.verdict)}</div>
    ${data.quote ? `<blockquote class="ann-quote">${esc(data.quote)}</blockquote>` : ''}
    <table class="grid"><thead><tr><th>#</th><th>Результат</th><th>Совпало терминов</th><th>Прогон</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

function renderAblation(data) {
  const rows = data.variants.map((variant) => `
    <tr class="${variant.dropped === null ? 'row-same' : (variant.reproduced ? 'row-regressed' : 'row-improved')}">
      <td>${esc(variant.label)}</td>
      <td>${variant.reproduced ? 'ошибка осталась' : 'ошибка исчезла'}</td>
      <td class="num">${variant.terms.share === null ? '—' : (variant.terms.share * 100).toFixed(0) + '%'}</td>
      <td class="mono">${esc(variant.run_id)}</td>
    </tr>`).join('');
  return `
    <div class="verdict ${data.culprits.length ? 'verdict-good' : 'verdict-neutral'}">${esc(data.verdict)}</div>
    ${data.quote ? `<blockquote class="ann-quote">${esc(data.quote)}</blockquote>` : ''}
    <table class="grid"><thead><tr><th>Вариант</th><th>Результат</th><th>Совпало терминов</th><th>Прогон</th></tr></thead>
    <tbody>${rows}</tbody></table>`;
}

/* ---------- журнал и накопленные замечания ---------- */

async function loadLog() {
  const runs = await api('/api/runs?limit=200');
  const visible = runs.filter((run) => run.suite !== 'probe');
  document.querySelector('#runs-table tbody').innerHTML = visible.map((run) => `
    <tr>
      <td class="mono">${esc(run.ts.slice(0, 16).replace('T', ' '))}</td>
      <td>${esc(run.profile_name || run.profile)}</td>
      <td class="clip" title="${esc(run.question)}">${esc(run.question)}</td>
      <td class="num">${run.annotations_count || ''}</td>
      <td>${run.clean ? '<span class="badge badge-good">чистый</span>' : `<span class="badge badge-warn">${run.deviations}</span>`}</td>
      <td><button class="btn btn-sm" data-open-run="${esc(run.id)}">Открыть и разметить</button></td>
    </tr>`).join('') || '<tr><td colspan="6" class="dim">Прогонов пока нет.</td></tr>';

  const data = await api('/api/annotations');
  if (!data.total) {
    $('findings-body').innerHTML = '<p class="dim">Замечаний пока нет.</p>';
    return;
  }
  const maxCount = Math.max(...data.by_category.map((item) => item.count), 1);
  const categories = data.by_category.map((item) => `
    <div class="comp-row">
      <div class="comp-top"><span>${esc(item.label)}</span><span class="comp-num">${item.count}</span></div>
      <div class="meter"><div class="meter-fill" style="width:${(100 * item.count / maxCount).toFixed(1)}%"></div></div>
    </div>`).join('');

  $('findings-body').innerHTML = `
    <div class="section-label">Накоплено замечаний: ${data.total} на ${data.runs_annotated} прогонах</div>
    <div class="diff-grid">
      <div class="card"><div class="card-title">Что повторяется чаще всего</div>${categories}</div>
      <div class="card"><div class="card-title">В какой части ответа</div>
        <div class="card-body"><div class="chip-row">${data.by_part.map((item) =>
          `<span class="badge badge-muted">${esc(item.label)}: ${item.count}</span>`).join(' ')}</div>
          <dl class="kv">
            <dt>для разбора</dt><dd>${esc(data.stream_path)}</dd>
            <dt>для чтения</dt><dd>${esc(data.digest_path)}</dd>
          </dl>
        </div>
      </div>
    </div>`;
}

/* Открывает прошлый прогон в чате, чтобы доразметить его. */
async function openRun(runId) {
  switchTab('chat');

  // Прогон уже на экране — не плодим вторую карточку того же ответа.
  const existing = answerByRun(runId);
  if (existing) {
    existing.card.wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
    renderMarksRail(runId);
    document.querySelector('.seg[data-rail="marks"]').click();
    return;
  }

  const record = await api('/api/run/' + runId);
  dropEmptyState();

  addUserMessage(record.input.user_message);
  const card = addAnswerCard(record.profile.name + ' · из журнала');
  card.head.textContent = runId;
  card.body.classList.remove('streaming');
  const text = (record.response || {}).text || '';
  card.body.textContent = text;

  const answer = registerAnswer(runId, card, text, record.annotations || [], {
    start: {
      prompt: record.prompt,
      request: record.request,
      git: record.git,
    },
    done: {
      response: record.response,
      checks: record.checks,
      checks_summary: record.checks_summary,
      deviations: (record.prompt || {}).deviations,
    },
  });
  renderMarksRail(runId);
  renderWhyRail(answer);
  scrollChat();
}

/* ---------- вкладки и события ---------- */

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((tab) => tab.classList.toggle('tab-active', tab.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach((panel) =>
    panel.classList.toggle('tab-panel-active', panel.id === 'tab-' + name));
  if (name === 'log') loadLog();
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
      $('rail-title').textContent = marks ? 'Замечания к ответу' : 'Почему так вышло';
    });
  });

  $('send-btn').addEventListener('click', send);
  $('input').addEventListener('keydown', (event) => {
    if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) send();
  });
  $('clear-btn').addEventListener('click', () => {
    state.messages = [];
    state.answers = [];
    $('messages').innerHTML = '<div class="empty-state"><p class="dim">Диалог очищен, история для API сброшена. Прогоны и замечания остались в журнале.</p></div>';
    renderMarksRail();
  });

  $('profile-select').addEventListener('change', () => { showProfileNote(); applyModelCaps(); });
  $('model-input').addEventListener('change', applyModelCaps);
  $('reload-btn').addEventListener('click', async () => {
    await loadProfiles();
    await loadMeta();
    toast('Профили перечитаны с диска');
  });

  $('preview-btn').addEventListener('click', async () => {
    const profile = currentProfile();
    if (!profile) return;
    try {
      const data = await postJSON('/api/preview', {
        profile: profile.id,
        message: $('input').value || '(пример вопроса)',
        overrides: overrides(),
      });
      renderWhyRail({ meta: { start: { prompt: data.prompt, request: data.request, git: data.git } }, annotations: [] });
      document.querySelector('.seg[data-rail="log"]').click();
    } catch (error) { toast(error.message, 'bad'); }
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
    const starter = event.target.closest('[data-starter]');
    if (starter) {
      $('input').value = starter.dataset.starter;
      $('input').focus();
      return;
    }

    const probe = event.target.closest('[data-probe]');
    if (probe) return runProbe(probe.dataset.probe, probe.dataset.run, Number(probe.dataset.index));

    const del = event.target.closest('[data-del-ann]');
    if (del) return deleteAnnotation(del.dataset.delAnn, Number(del.dataset.index));

    const open = event.target.closest('[data-open-run]');
    if (open) return openRun(open.dataset.openRun);

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
    }
  });

  $('log-refresh').addEventListener('click', loadLog);
  $('log-digest').addEventListener('click', async () => {
    const data = await postJSON('/api/annotations/digest', {});
    toast('Сводка собрана: ' + data.path);
  });
}

init();
