// Сборка двух PPTX для адборда «Фиксация антиангинальной пары БАБ + ДГП-БКК».
//   1) v1-edited: исходные 5 слайдов докладчика с точечными правками по итогам совета;
//   2) v2-draft: черновик v2 (7 слайдов + 2 бэкапа).
// Запуск (нужны pptxgenjs и путь к apply_theme.js из скилла pptx):
//   NODE_PATH=<node_modules с pptxgenjs> APPLY_THEME=<.../scripts/apply_theme.js> node build.js
const path = require("path");
const pptxgen = require("pptxgenjs");
const { applyTheme } = require(process.env.APPLY_THEME);

const OUT = __dirname;
const THEME = {
  name: "Adboard FDC",
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  colors: {
    dk1: "252A31", lt1: "FFFFFF", dk2: "0D5A8C", lt2: "F5F7FA",
    accent1: "0D5A8C", accent2: "0B4A74", accent3: "0A9FD6", accent4: "F2B627",
    accent5: "E3A91C", accent6: "5B6470", hlink: "0D5A8C", folHlink: "5B6470",
  },
};
// Оттенки, которых нет в теме (hex): заливки плашек и семантика.
const HX = {
  callout: "E5EFF5", note: "FDF5DC", ok: "E3F1E8", okInk: "2A7448", warn: "FBEFD5", warnInk: "8F5C00",
  red: "B0423F", caps: "7F8A96", low: "DFE5EB", ph: "FFE6A8", greyNum: "5E7A91", qmark: "9CC9E6",
  diverge: "FFFAF0", line: "D9DFE6",
};

const L = 0.8, W = 11.733; // левое поле и ширина контента, слайд 13,333 × 7,5 дюйма

function makePres(tagText) {
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  pres.theme = { headFontFace: THEME.headFontFace, bodyFontFace: THEME.bodyFontFace };
  pres.author = "Merck Medical Affairs (черновик)";
  const C = pres.SchemeColor;
  const common = (tag, tagColor) => ({
    background: { color: C.background2 },
    objects: [
      { text: { text: tag, options: { x: 7.0, y: 0.12, w: 6.1, h: 0.3, fontSize: 9, color: tagColor, align: "right", margin: 0 } } },
    ],
    slideNumber: { x: 12.6, y: 7.08, w: 0.5, h: 0.25, fontSize: 9, color: C.accent6, align: "right" },
  });
  // pptxgenjs мутирует объекты опций — для каждого макета строим свежие.
  const placeholders = () => [
    { placeholder: { options: { name: "title", type: "title", x: L, y: 0.42, w: W, h: 1.0, fontSize: 24, bold: true, color: C.accent1, align: "left", valign: "top", margin: 0 }, text: "" } },
    { placeholder: { options: { name: "foot", type: "body", x: L, y: 6.5, w: W - 0.6, h: 0.82, fontSize: 9, color: C.accent6, valign: "bottom", margin: 0 }, text: "" } },
  ];
  const layout = (title, tag, tagColor) => {
    const base = common(tag, tagColor);
    pres.defineSlideMaster({ title, background: base.background, slideNumber: base.slideNumber, objects: [...base.objects, ...placeholders()] });
  };
  layout("CONTENT", tagText, C.accent6);
  layout("BACKUP", "Бэкап · только по вопросу из зала · решение по использованию за Евгением", HX.warnInk);
  return { pres, C };
}

// ---------- примитивы ----------
function H(pres, C) {
  const S = pres.shapes;
  const shadow = () => ({ type: "outer", color: "1E3246", opacity: 0.12, blur: 3, offset: 1, angle: 90 });
  const api = {
    text(slide, text, o) {
      slide.addText(text, Object.assign({ isTextBox: true, margin: 0, fontSize: 14, color: C.text1, valign: "top", fontFace: undefined }, o));
    },
    card(slide, x, y, w, h, name, o = {}) {
      slide.addShape(S.ROUNDED_RECTANGLE, Object.assign({ x, y, w, h, rectRadius: 0.08, fill: { color: C.background1 }, line: { type: "none" }, shadow: shadow(), objectName: name }, o));
    },
    topBar(slide, x, y, w, name) {
      slide.addShape(S.RECTANGLE, { x, y, w, h: 0.07, fill: { color: C.accent1 }, line: { type: "none" }, objectName: name });
    },
    leftBox(slide, x, y, w, h, fill, bar, name) {
      slide.addShape(S.RECTANGLE, { x, y, w, h, fill: { color: fill }, line: { type: "none" }, objectName: name });
      slide.addShape(S.RECTANGLE, { x, y, w: 0.07, h, fill: { color: bar }, line: { type: "none" }, objectName: name + " — полоса" });
    },
    pillW(text, size) { return text.length * size * 0.64 / 72 + 0.3; },
    pill(slide, x, y, text, kind, size = 12, h = 0.34) {
      const fills = { bab: C.accent2, dhp: C.accent3, raas: C.accent4 };
      const ink = kind === "raas" ? "2B2100" : C.background1;
      const w = api.pillW(text, size);
      slide.addText(text, { shape: S.ROUNDED_RECTANGLE, x, y, w, h, rectRadius: h / 2, fill: { color: fills[kind] }, color: ink, bold: true, fontSize: size, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "Пилюля: " + text });
      return w;
    },
    capsule(slide, x, y, items, size = 12) {
      const pad = 0.06, h = 0.34;
      let w = pad;
      items.forEach(([t]) => { w += api.pillW(t, size) + pad; });
      slide.addShape(S.ROUNDED_RECTANGLE, { x, y: y - pad, w, h: h + 2 * pad, rectRadius: (h + 2 * pad) / 2, fill: { color: C.background1 }, line: { color: HX.caps, width: 1.75 }, objectName: "Таблетка: " + items.map(i => i[0]).join(" + ") });
      let cx = x + pad;
      items.forEach(([t, k]) => { cx += api.pill(slide, cx, y, t, k, size, h) + pad; });
      return w;
    },
    bar(slide, x, y, w, h, runs, size = 15) {
      api.leftBox(slide, x, y, w, h, HX.note, C.accent5, "Плашка");
      api.text(slide, runs, { x: x + 0.3, y, w: w - 0.5, h, fontSize: size, valign: "middle" });
    },
    callout(slide, x, y, w, h, runs, size = 15) {
      api.leftBox(slide, x, y, w, h, HX.callout, C.accent1, "Выноска");
      api.text(slide, runs, { x: x + 0.3, y, w: w - 0.5, h, fontSize: size, valign: "middle" });
    },
    foot(slide, lines) {
      const runs = lines.map((t, i) => ({ text: t, options: { breakLine: i < lines.length - 1 } }));
      slide.addText(runs, { placeholder: "foot", bullet: false });
    },
    title(slide, t) { slide.addText(t, { placeholder: "title" }); },
  };
  return api;
}

const REF = {
  cad: "Барбараш О.Л. и соавт. Стабильная ишемическая болезнь сердца. Клинические рекомендации 2024. Российский кардиологический журнал. 2024;29(9):6110. doi:10.15829/1560-4071-2024-6110",
  cadS: "Барбараш О.Л. и соавт. Стабильная ИБС. КР 2024. РКЖ. 2024;29(9):6110",
  esc: "Vrints C, et al. 2024 ESC Guidelines for the management of chronic coronary syndromes. Eur Heart J. 2024;45:3415–3537. doi:10.1093/eurheartj/ehae177",
  escS: "Vrints C, et al. Eur Heart J. 2024;45:3415–3537",
  ag: "Кобалава Ж.Д. и соавт. Артериальная гипертензия у взрослых. Клинические рекомендации 2024. Российский кардиологический журнал. 2024;29(9):6117. doi:10.15829/1560-4071-2024-6117",
  agS: "Кобалава Ж.Д. и соавт. АГ у взрослых. КР 2024. РКЖ. 2024;29(9):6117",
  skib: "Скибицкий В.В. и соавт. Эффективность фиксированной комбинации бисопролола и амлодипина у пациентов с артериальной гипертонией, ишемической болезнью сердца и метаболическим синдромом. Системные гипертензии. 2015;12(1):26–31. doi:10.26442/SG29086",
  ema: "European Medicines Agency. Guideline on clinical development of fixed combination medicinal products. EMA/CHMP/158268/2017. Принято CHMP 23.03.2017, действует с 01.10.2017",
  belsey: "Belsey J, et al. Relative efficacy of antianginal drugs used as add-on therapy in patients with stable angina: a systematic review and meta-analysis. Eur J Prev Cardiol. 2015;22(7):837–848. doi:10.1177/2047487314533217",
  abbr: "БАБ, ББ — бета-адреноблокаторы; (ДГП-)БКК, АК — (дигидропиридиновые) блокаторы кальциевых каналов; ФК — функциональный класс; ЕОК — класс рекомендации ESC; УУР / УДД — уровень убедительности рекомендаций / достоверности доказательств",
};

// ---------- общие блоки ----------
function fourCards(h, slide, C, y, cards, numFmt) {
  const gap = 0.25, cw = (W - 3 * gap) / 4, ch = 2.05;
  cards.forEach(([head, body], i) => {
    const x = L + i * (cw + gap);
    h.card(slide, x, y, cw, ch, "Карточка " + (i + 1));
    h.topBar(slide, x, y, cw, "Карточка " + (i + 1) + " — верх");
    h.text(slide, numFmt(i + 1), { x: x + 0.22, y: y + 0.22, w: 1, h: 0.4, fontSize: 22, bold: true, color: C.accent1 });
    h.text(slide, head, { x: x + 0.22, y: y + 0.66, w: cw - 0.36, h: 0.35, fontSize: 14, bold: true });
    h.text(slide, body, { x: x + 0.22, y: y + 1.04, w: cw - 0.4, h: 0.95, fontSize: 13.5, color: "3A414B" });
  });
}

function skibitskyBlock(h, slide, C, top) {
  h.card(slide, L, top, 6.95, 3.55, "Скибицкий — данные");
  h.text(slide, "Группа 1, n=30", { x: L + 0.25, y: top + 0.28, w: 1.7, h: 0.34, fontSize: 13.5, bold: true, valign: "middle" });
  let x = L + 2.05;
  x += h.capsule(slide, x, top + 0.28, [["бисопролол", "bab"], ["амлодипин", "dhp"]]) + 0.1;
  h.text(slide, "+", { x, y: top + 0.28, w: 0.2, h: 0.34, fontSize: 14, bold: true, valign: "middle" }); x += 0.25;
  h.pill(slide, x, top + 0.28, "рамиприл", "raas");
  h.text(slide, "Группа 2, n=31", { x: L + 0.25, y: top + 0.88, w: 1.7, h: 0.34, fontSize: 13.5, bold: true, valign: "middle" });
  x = L + 2.05;
  [["БАБ", "bab"], ["ДГП-БКК", "dhp"], ["иАПФ", "raas"]].forEach(([t, k], i) => {
    x += h.pill(slide, x, top + 0.88, t, k) + 0.08;
    if (i < 2) { h.text(slide, "+", { x, y: top + 0.88, w: 0.2, h: 0.34, fontSize: 14, bold: true, valign: "middle" }); x += 0.24; }
  });
  h.text(slide, [{ text: "молекулы в группе 2 — уточнить по полному тексту", options: { highlight: HX.ph } }], { x: L + 2.05, y: top + 1.28, w: 4.6, h: 0.25, fontSize: 10.5, color: HX.warnInk, bold: true });
  slide.addShape(pres_shapes(slide).LINE, { x: L + 0.25, y: top + 1.68, w: 6.45, h: 0, line: { color: C.accent1, width: 1.5 }, objectName: "Разделитель" });
  h.text(slide, "Приступы стенокардии в неделю, исходно → 12 недель", { x: L + 0.25, y: top + 1.78, w: 6.45, h: 0.32, fontSize: 14, bold: true, align: "center" });
  h.text(slide, "Фиксированная схема", { x: L + 0.25, y: top + 2.15, w: 3.2, h: 0.28, fontSize: 12, color: C.accent6, align: "center" });
  h.text(slide, "Свободная схема", { x: L + 3.5, y: top + 2.15, w: 3.2, h: 0.28, fontSize: 12, color: C.accent6, align: "center" });
  h.text(slide, "3,83 → 0,20", { x: L + 0.25, y: top + 2.42, w: 3.2, h: 0.55, fontSize: 28, bold: true, color: C.accent1, align: "center" });
  h.text(slide, "4,29 → 1,03", { x: L + 3.5, y: top + 2.42, w: 3.2, h: 0.55, fontSize: 28, bold: true, color: HX.greyNum, align: "center" });
  h.text(slide, "АД через 12 недель сопоставимо: 125/79 и 127/78 мм рт. ст.", { x: L + 0.25, y: top + 3.08, w: 6.45, h: 0.3, fontSize: 12, color: C.accent6 });
  const rx = L + 7.2, rw = W - 7.2;
  h.callout(slide, rx, top, rw, 1.75, [
    { text: "Фиксированная комбинация бисопролола и амлодипина зарегистрирована для лечения АГ (замещение монокомпонентов в тех же дозах). " },
    { text: "Данные получены у пациентов с АГ, стабильной стенокардией II–III ФК и метаболическим синдромом", options: { bold: true } },
  ], 13.5);
  h.bar(slide, rx, top + 1.95, rw, 1.15, [
    { text: "Сравнивались фиксированная и свободная тройка, а не способы фиксации. Межгрупповое сравнение: " },
    { text: "p — уточнить по полному тексту", options: { bold: true, highlight: HX.ph } },
  ], 13.5);
}
let _pres; function pres_shapes() { return _pres.shapes; }

// =====================================================================
// 1) Исходная дека с правками
// =====================================================================
async function buildV1() {
  const { pres, C } = makePres("Исходная дека с правками по итогам совета · адборд · не для полевого использования");
  _pres = pres;
  const h = H(pres, C);
  const S = pres.shapes;
  pres.title = "Адборд: фиксация антиангинальной пары — исходная дека с правками";
  pres.addSection({ title: "Дека адборда (5 слайдов, с правками)" });
  const sec = "Дека адборда (5 слайдов, с правками)";

  // --- 1
  let s = pres.addSlide({ masterName: "CONTENT", sectionTitle: sec });
  h.title(s, "Рациональный выбор фиксированной комбинации: от клинической задачи к составу препарата");
  h.text(s, [
    { text: "Рациональность фиксированной комбинации определяется " },
    { text: "клинической обоснованностью совместного применения компонентов", options: { bold: true } },
    { text: ", их соответствием терапевтической задаче, выбранным дозам, профилю безопасности и возможностью упростить лечение" },
  ], { x: L, y: 1.55, w: W, h: 0.85, fontSize: 16 });
  fourCards(h, s, C, 2.6, [
    ["Клиническая задача", "Какая задача ведущая у этого пациента: симптомы или АД и прогноз?"],
    ["Выбор компонентов", "Обоснован ли вклад каждого препарата в эту задачу?"],
    ["Дозы и безопасность", "Соответствуют ли дозы и переносимость конкретному пациенту?"],
    ["Управляемость схемы", "Можно ли скорректировать один препарат, не меняя остальные?"],
  ], n => "0" + n);
  h.callout(s, L, 4.95, W, 1.25, [
    { text: "Рациональная фиксированная комбинация", options: { bold: true, breakLine: false } },
    { text: " — не обязательно единственно возможная или доказанно лучшая, а клинически обоснованная для конкретного пациента", options: { italic: true, breakLine: true } },
    { text: "Рабочее определение. Согласуется с принципами EMA: сочетание и вклад каждого компонента должны быть обоснованы, а упрощения схемы самого по себе для этого недостаточно¹", options: { fontSize: 12, color: C.accent6 } },
  ], 15);
  h.foot(s, ["1. " + REF.ema]);
  s.addNotes("Правки относительно исходного слайда: карточка 01 — вопрос «какая задача ведущая: симптомы или АД и прогноз»; карточка 04 переименована в «Управляемость схемы» — «можно ли скорректировать один препарат, не меняя остальные». Ссылка на EMA оставлена в сноске; аргумент на ней не строить: оппонент спросит, что зарегистрировал регулятор (АГ).");

  // --- 2
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: sec });
  h.title(s, "БАБ + ДГП-БКК: от обоснованного выбора антиангинальных компонентов к вопросу их совместного применения");
  const fx = L, fw = 6.1;
  h.card(s, fx, 1.6, fw, 0.72, "Пациент");
  h.text(s, [{ text: "Пациент: ", options: { bold: true } }, { text: "ИБС, стабильная стенокардия напряжения, сопутствующая АГ" }], { x: fx + 0.22, y: 1.6, w: fw - 0.4, h: 0.72, fontSize: 14, valign: "middle" });
  h.text(s, "↓", { x: fx + fw / 2 - 0.2, y: 2.34, w: 0.4, h: 0.3, fontSize: 16, color: HX.caps, align: "center" });
  h.card(s, fx, 2.66, fw, 0.72, "Индивидуальная оценка");
  h.text(s, [{ text: "Индивидуальная оценка: ", options: { bold: true } }, { text: "симптомы, ЧСС, АД, сопутствующие заболевания, переносимость" }], { x: fx + 0.22, y: 2.66, w: fw - 0.4, h: 0.72, fontSize: 14, valign: "middle" });
  h.text(s, "↓", { x: fx + fw / 2 - 0.2, y: 3.4, w: 0.4, h: 0.3, fontSize: 16, color: HX.caps, align: "center" });
  const bw = (fw - 0.45) / 2;
  [[fx, "БАБ", C.accent2], [fx + bw + 0.45, "ДГП-БКК", C.accent3]].forEach(([bx, t, col]) => {
    s.addText([{ text: t, options: { fontSize: 18, bold: true, breakLine: true } }, { text: "антиангинальный компонент", options: { fontSize: 12 } }], { shape: S.ROUNDED_RECTANGLE, x: bx, y: 3.72, w: bw, h: 0.82, rectRadius: 0.08, fill: { color: col }, color: C.background1, margin: [14, 14, 0, 0], valign: "middle", isTextBox: true, objectName: t });
  });
  h.text(s, "+", { x: fx + bw, y: 3.72, w: 0.45, h: 0.82, fontSize: 20, bold: true, color: C.accent6, align: "center", valign: "middle" });
  h.text(s, "↓", { x: fx + fw / 2 - 0.2, y: 4.56, w: 0.4, h: 0.3, fontSize: 16, color: HX.caps, align: "center" });
  h.callout(s, fx, 4.88, fw, 0.52, [{ text: "Оба компонента выбраны, дозы подобраны", options: { bold: true, color: C.accent1 } }], 15);
  const rx = 7.3, rw = L + W - rx;
  h.text(s, "ОПОРА В РЕКОМЕНДАЦИЯХ", { x: rx, y: 1.6, w: rw, h: 0.3, fontSize: 13, bold: true, color: C.accent1, charSpacing: 1 });
  [
    ["КР МЗ РФ 2024¹ · ЕОК I C; УУР C, УДД 5", "Стенокардия III–IV ФК: при отсутствии противопоказаний — сразу БАБ + ДГП-БКК для достижения I ФК"],
    ["ESC 2024² · IIa B", "Симптомы не контролируются монотерапией БАБ или БКК: следует рассмотреть БАБ + ДГП-БКК, если нет противопоказаний"],
    ["КР МЗ РФ, АГ 2024³ · ЕОК/ЕОАГ I A; УУР А, УДД 1", "Пациентам с АГ и симптомами стенокардии рекомендуются ББ и/или АК"],
  ].forEach(([src, body], i) => {
    const y = 1.98 + i * 1.1;
    h.card(s, rx, y, rw, 1.04, "Рекомендация " + (i + 1));
    h.text(s, src, { x: rx + 0.2, y: y + 0.1, w: rw - 0.4, h: 0.25, fontSize: 11.5, bold: true, color: C.accent1 });
    h.text(s, body, { x: rx + 0.2, y: y + 0.37, w: rw - 0.4, h: 0.6, fontSize: 12.5 });
  });
  h.text(s, "Расхождение: КР МЗ РФ — при III–IV ФК пара сразу; ESC — после неуспеха монотерапии", { x: rx, y: 5.3, w: rw, h: 0.36, fontSize: 10.5, color: HX.warnInk, bold: true });
  h.bar(s, L, 5.72, W, 0.55, [{ text: "Рекомендации обосновывают " }, { text: "сочетание классов и упрощение схемы (ESC, I B)²", options: { bold: true } }, { text: ", но не выбор пары для фиксации" }], 14);
  h.foot(s, [REF.abbr, "1. " + REF.cad, "2. " + REF.esc, "3. " + REF.ag]);
  s.addNotes("Правки: жёлтая плашка исправлена — в ESC 2024 CCS есть рекомендация I B за упрощение схемы, в т. ч. с помощью фиксированных комбинаций, для приверженности; исходная формулировка «не обосновывают фиксированную форму» была неточной. Добавлена карточка КР АГ 2024 (ББ и/или АК при АГ и стенокардии, I A) — опора, что ДГП-БКК в тройке именно из-за стенокардии. Добавлена строка о расхождении КР и ESC. Исходные цитаты КР (I C) и ESC (IIa B) сверены с первоисточниками.");

  // --- 3
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: sec });
  h.title(s, "Какие компоненты целесообразно объединять в фиксированную комбинацию, если ведущая задача — контроль стенокардии?");
  h.text(s, "Условный пациент: БАБ + ДГП-БКК — по стенокардии, блокатор РААС — для профилактики ССО¹", { x: L, y: 1.47, w: W, h: 0.32, fontSize: 14, color: C.accent6 });
  const col = { v: [L, 0.85], t1: [L + 0.85, 3.05], t2: [L + 3.9, 1.95], c: [L + 5.95, 2.95], b: [L + 8.95, W - 8.95] };
  const hdr = { v: "Вариант", t1: "Таблетка 1: фиксированная комбинация", t2: "Таблетка 2", c: "При коррекции блокатора РААС (K⁺, креатинин, кашель)", b: "При брадикардии или отёках на амлодипине" };
  Object.keys(col).forEach(k => h.text(s, hdr[k], { x: col[k][0] + 0.1, y: 1.85, w: col[k][1] - 0.1, h: 0.45, fontSize: 11.5, bold: true, color: C.accent6, valign: "bottom" }));
  const rows = [
    ["А", [["БАБ", "bab"], ["ДГП-БКК", "dhp"]], [["Блокатор РААС", "raas"]], ["Антиангинальная таблетка не меняется", true], ["Меняется FDC", false]],
    ["Б", [["БАБ", "bab"], ["Блокатор РААС", "raas"]], [["ДГП-БКК", "dhp"]], ["Меняется FDC: заменить монопрепаратом БАБ", false], ["Брадикардия — FDC; отёки — таблетка 2", null]],
    ["В", [["ДГП-БКК", "dhp"], ["Блокатор РААС", "raas"]], [["БАБ", "bab"]], ["Меняется FDC с ДГП-БКК", false], ["Брадикардия — таблетка 2; отёки — FDC", null]],
  ];
  rows.forEach(([v, t1, t2, c, b], i) => {
    const y = 2.38 + i * 0.78;
    if (i === 0) h.leftBox(s, L, y, W, 0.68, HX.callout, C.accent1, "Строка А");
    else s.addShape(S.RECTANGLE, { x: L, y, w: W, h: 0.68, fill: { color: C.background1 }, line: { type: "none" }, objectName: "Строка " + v });
    h.text(s, v, { x: col.v[0] + 0.15, y, w: 0.45, h: 0.68, fontSize: 22, bold: true, color: C.accent1, valign: "middle" });
    h.capsule(s, col.t1[0] + 0.1, y + 0.17, t1);
    h.capsule(s, col.t2[0] + 0.1, y + 0.17, t2);
    const tone = ok => ok === true ? HX.okInk : ok === false ? HX.warnInk : C.text1;
    h.text(s, c[0], { x: col.c[0] + 0.1, y, w: col.c[1] - 0.15, h: 0.68, fontSize: 12.5, bold: true, color: tone(c[1]), valign: "middle" });
    h.text(s, b[0], { x: col.b[0] + 0.1, y, w: col.b[1] - 0.15, h: 0.68, fontSize: 12.5, bold: true, color: tone(b[1]), valign: "middle" });
  });
  const dw = (W - 0.3) / 2;
  [["Что назначить?", "Выбор БАБ + ДГП-БКК для контроля стенокардии; блокатора РААС — по соответствующим показаниям"], ["Что объединить?", "Выбор состава фиксированной комбинации — отдельное решение, зависящее от клинической задачи"]].forEach(([hd, body], i) => {
    const x = L + i * (dw + 0.3);
    s.addShape(S.ROUNDED_RECTANGLE, { x, y: 4.82, w: dw, h: 1.05, rectRadius: 0.12, fill: { color: C.accent2 }, line: { type: "none" }, objectName: hd });
    h.text(s, [{ text: hd, options: { bold: true, fontSize: 15, breakLine: true } }, { text: body, options: { fontSize: 13.5 } }], { x: x + 0.25, y: 4.82, w: dw - 0.5, h: 1.05, color: C.background1, valign: "middle", paraSpaceAfter: 3 });
  });
  h.leftBox(s, L, 6.0, W, 0.62, HX.note, C.accent5, "Плашка");
  h.text(s, [
    { text: "Назначение трёх классов не предопределяет единственно возможный способ объединения их в две таблетки", options: { bullet: true, breakLine: true } },
    { text: "Прямых сравнительных данных о превосходстве одного способа фиксации над другим нет", options: { bullet: true } },
  ], { x: L + 0.3, y: 6.0, w: W - 0.5, h: 0.62, fontSize: 13, valign: "middle" });
  h.foot(s, ["РААС — ренин-ангиотензин-альдостероновая система; ССО — сердечно-сосудистые осложнения; FDC — фиксированная комбинация", "1. " + REF.cadS + " — разделы 3.1.2.1 (устранение симптомов) и 3.1.2.2 (профилактика ССО, иАПФ/БРА при АГ — ЕОК I A; УУР C, УДД 5)"]);
  s.addNotes("Правки: колонка «Антиангинальная пара: в одной таблетке / разнесены» (тавтология) заменена колонками последствий. Логика: при коррекции блокатора РААС в варианте А антиангинальная таблетка не меняется; в Б и В меняется FDC. Честно показана обратная сторона: при брадикардии или отёках на амлодипине в варианте А меняется именно FDC. Подзаголовок: вместо «три необходимых класса» — откуда каждый класс. В заголовок добавлено тире. «Недостаточно» → «нет» (сравнений нет). Значки ❑ заменены обычными маркерами.");

  // --- 4
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: sec });
  h.title(s, "Фиксация антиангинальной пары на фоне терапии блокаторами РААС: клинический опыт");
  h.text(s, "Скибицкий и соавт., 2015¹ · открытое РКИ · n=61 · АГ + стабильная стенокардия II–III ФК + метаболический синдром · 12 недель", { x: L, y: 1.47, w: W, h: 0.32, fontSize: 14, color: C.accent6 });
  skibitskyBlock(h, s, C, 1.95);
  s.addShape(S.ROUNDED_RECTANGLE, { x: L, y: 5.68, w: W, h: 0.72, rectRadius: 0.12, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "Вывод" });
  h.text(s, "Терапия с фиксированной антиангинальной парой на фоне иАПФ сопровождалась улучшением контроля стенокардии. Способы фиксации напрямую не сравнивались", { x: L + 0.3, y: 5.68, w: W - 0.6, h: 0.72, fontSize: 15, color: C.background1, align: "center", valign: "middle" });
  h.foot(s, ["иАПФ — ингибитор ангиотензинпревращающего фермента", "1. " + REF.skib]);
  s.addNotes("Правки: удалён Divchev 2017 (другая пара — метопролол + ивабрадин; ивабрадин как дополнительная терапия при ФВ ЛЖ >40% без СН в ESC 2024 — III B, в КР МЗ РФ — 2-я линия; исследование без контроля; FDC другой компании). Удалена фармакоэкономика (цены 2014 года). Добавлен дисклеймер «получены у» (правило 4 репо). Итоговая плашка переписана: исследование сравнивает FDC со свободной тройкой, а не способы фиксации. Перед адбордом уточнить по полному тексту молекулы в группе 2 и межгрупповой p (жёлтые плейсхолдеры).");

  // --- 5
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: sec });
  h.title(s, "Когда фиксация двух антиангинальных компонентов является рациональным выбором?");
  const gw = 0.55, cw3 = (W - 2 * gw) / 3;
  [
    ["Клиническая задача", "У пациента с ИБС и АГ ведущей задачей является контроль симптомов стенокардии или её эквивалентов при подтверждённой ишемии"],
    ["Обоснованный выбор компонентов", "Для контроля стенокардии уже выбраны БАБ + ДГП-БКК, дозы подобраны и соответствуют дозировкам фиксированной комбинации, переносимость подтверждена"],
    ["Рациональная организация лечения", "Совместная фиксация БАБ + ДГП-БКК объединяет оба антиангинальных компонента; коррекция блокатора РААС, назначенного отдельно по показаниям, не затрагивает антиангинальную пару"],
  ].forEach(([hd, body], i) => {
    const x = L + i * (cw3 + gw);
    h.card(s, x, 1.55, cw3, 2.85, "Шаг " + (i + 1));
    h.topBar(s, x, 1.55, cw3, "Шаг " + (i + 1) + " — верх");
    h.text(s, String(i + 1), { x: x + 0.25, y: 1.78, w: 0.5, h: 0.4, fontSize: 22, bold: true, color: C.accent1 });
    h.text(s, hd, { x: x + 0.25, y: 2.2, w: cw3 - 0.45, h: 0.55, fontSize: 15, bold: true });
    h.text(s, body, { x: x + 0.25, y: 2.8, w: cw3 - 0.45, h: 1.55, fontSize: 12.5 });
    if (i < 2) h.text(s, "→", { x: x + cw3, y: 2.6, w: gw, h: 0.4, fontSize: 22, color: HX.caps, align: "center" });
  });
  s.addShape(S.ROUNDED_RECTANGLE, { x: L, y: 4.55, w: W, h: 1.22, rectRadius: 0.12, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "Положение для обсуждения" });
  h.text(s, [
    { text: "ПОЛОЖЕНИЕ ДЛЯ ОБСУЖДЕНИЯ", options: { fontSize: 11, bold: true, color: HX.qmark, charSpacing: 1, breakLine: true } },
    { text: "При уже обоснованном выборе БАБ + ДГП-БКК их совместная фиксация — один из " },
    { text: "клинически рациональных вариантов", options: { bold: true } },
    { text: " организации антиангинальной терапии у пациента со стенокардией и сопутствующей АГ" },
  ], { x: L + 0.3, y: 4.55, w: W - 0.6, h: 1.22, fontSize: 16, color: C.background1, valign: "middle", paraSpaceAfter: 4 });
  h.card(s, L, 5.9, W, 0.58, "Не вариант А");
  h.text(s, [
    { text: "Не вариант А: ", options: { bold: true, color: HX.red } },
    { text: "АГ без стенокардии (FDC с блокатором РААС по КР АГ) · ЧСС <60 на подобранных дозах · ХСН со сниженной ФВ · отёки на амлодипине" },
  ], { x: L + 0.25, y: 5.9, w: W - 0.5, h: 0.58, fontSize: 12.5, valign: "middle" });
  h.foot(s, [
    "Выбор индивидуален и учитывает дозы, безопасность и зарегистрированные показания. Сравнительное превосходство способов фиксации не доказано",
    "Положение выходит за пределы зарегистрированных показаний FDC бисопролол + амлодипин (АГ, замещение монокомпонентов); материал для научной дискуссии",
  ]);
  s.addNotes("Правки: «Итоговое положение» → «Положение для обсуждения» и off-label-сноска. Шаг 1 — «стенокардия или её эквиваленты при подтверждённой ишемии». Шаг 3 — коррекция блокатора РААС не затрагивает антиангинальную пару. Добавлена строка «Не вариант А» — прямой ответ на опасение докладчика: при АГ без стенокардии разговора о фиксации этой пары нет. В итоговое положение добавлено тире. Подготовить устно: в ОХЛП FDC «выраженная брадикардия (ЧСС менее 60)» стоит без «до начала терапии», а антиангинальная цель ЧСС 55–60 — нужен ответ медотдела.");

  const file = path.join(OUT, "2026-10-20_adboard-fdc-bab-amlo_v1-edited.pptx");
  await pres.writeFile({ fileName: file });
  await applyTheme(file, THEME);
  return file;
}

// =====================================================================
// 2) Черновик v2
// =====================================================================
async function buildV2() {
  const { pres, C } = makePres("Черновик v2 · адборд · не для полевого использования");
  _pres = pres;
  const h = H(pres, C);
  const S = pres.shapes;
  pres.title = "Адборд: фиксация антиангинальной пары — черновик v2";
  const main = "Основная дека", back = "Бэкап";
  pres.addSection({ title: main });

  // --- 1
  let s = pres.addSlide({ masterName: "CONTENT", sectionTitle: main });
  h.title(s, "Состав фиксированной комбинации выводится из ведущей клинической задачи");
  h.text(s, [{ text: "Фиксированная комбинация рациональна, когда каждый её компонент работает на ведущую задачу пациента, дозы уже подобраны, а схема остаётся " }, { text: "управляемой", options: { bold: true } }], { x: L, y: 1.5, w: W, h: 0.8, fontSize: 16 });
  fourCards(h, s, C, 2.5, [
    ["Ведущая задача", "Что ведущее у этого пациента: симптомы ишемии или контроль АД и прогноз?"],
    ["Вклад компонентов", "Работает ли каждый компонент таблетки на эту задачу?"],
    ["Дозы и переносимость", "Подобраны ли дозы на монокомпонентах и совпадают ли с дозировками FDC?"],
    ["Управляемость", "Можно ли скорректировать препарат с другой целью, не меняя остальные?"],
  ], n => String(n));
  h.callout(s, L, 4.85, W, 0.95, [{ text: "Рабочее определение. ", options: { bold: true } }, { text: "Рациональная фиксированная комбинация — клинически обоснованная для конкретного пациента, не обязательно единственно возможная. Упрощение схемы само по себе её не обосновывает¹" }], 15);
  h.foot(s, ["FDC — фиксированная комбинация (fixed-dose combination)", "1. " + REF.ema]);
  s.addNotes("«Сегодня вопрос не в том, можно ли комбинировать эти классы, — это решено. Вопрос в том, какую пару класть в одну таблетку, когда у пациента три класса».");

  // --- 2
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: main });
  h.title(s, "Рекомендации обосновывают пару БАБ + ДГП-БКК и упрощение схемы, но не говорят, какую пару фиксировать");
  const lw = 7.0, rx = L + lw + 0.3, rw = W - lw - 0.3;
  h.text(s, "ПАРА БАБ + ДГП-БКК ПРИ СТЕНОКАРДИИ", { x: L, y: 1.5, w: lw, h: 0.3, fontSize: 12.5, bold: true, color: C.accent1, charSpacing: 1 });
  h.text(s, "ФИКСИРОВАННАЯ ФОРМА", { x: rx, y: 1.5, w: rw, h: 0.3, fontSize: 12.5, bold: true, color: C.accent1, charSpacing: 1 });
  [
    ["КР МЗ РФ, стабильная ИБС 2024¹ · ЕОК I C; УУР C, УДД 5", "Стенокардия III–IV ФК: при отсутствии противопоказаний — сразу БАБ + ДГП-БКК для достижения ФК I"],
    ["КР МЗ РФ, стабильная ИБС 2024¹ · табл. ПА3-5", "Стандартная терапия, шаг 2: БАБ + ДГП-БКК"],
    ["ESC 2024² · IIa B", "Симптомы не контролируются монотерапией БАБ или БКК — следует рассмотреть БАБ + ДГП-БКК"],
    ["КР МЗ РФ, АГ 2024³ · ЕОК/ЕОАГ I A; УУР А, УДД 1", "Пациентам с АГ и симптомами стенокардии рекомендуются ББ и/или АК"],
  ].forEach(([src, body], i) => {
    const y = 1.85 + i * 0.95;
    h.card(s, L, y, lw, 0.87, "Рекомендация " + (i + 1));
    h.text(s, src, { x: L + 0.2, y: y + 0.09, w: lw - 0.4, h: 0.25, fontSize: 11.5, bold: true, color: C.accent1 });
    h.text(s, body, { x: L + 0.2, y: y + 0.35, w: lw - 0.4, h: 0.5, fontSize: 13 });
  });
  h.card(s, rx, 1.85, rw, 1.18, "ESC I B");
  h.text(s, "ESC 2024² · I B", { x: rx + 0.2, y: 1.94, w: rw - 0.4, h: 0.25, fontSize: 11.5, bold: true, color: C.accent1 });
  h.text(s, "Упрощение схемы, в том числе с помощью фиксированных комбинаций, рекомендуется для повышения приверженности", { x: rx + 0.2, y: 2.2, w: rw - 0.4, h: 0.8, fontSize: 13 });
  s.addShape(S.ROUNDED_RECTANGLE, { x: rx, y: 3.18, w: rw, h: 1.4, rectRadius: 0.08, fill: { color: HX.diverge }, line: { color: C.accent5, width: 1.5, dashType: "dash" }, objectName: "Расхождение" });
  h.text(s, "Расхождение КР МЗ РФ и ESC", { x: rx + 0.2, y: 3.28, w: rw - 0.4, h: 0.25, fontSize: 11.5, bold: true, color: HX.warnInk });
  h.text(s, "КР: при III–IV ФК пара назначается сразу. ESC: после неуспеха монотерапии; вопрос о стартовой комбинации ESC считает открытым", { x: rx + 0.2, y: 3.55, w: rw - 0.4, h: 1.0, fontSize: 13 });
  h.bar(s, L, 5.75, W, 0.52, [{ text: "Какую пару класть в одну таблетку, рекомендации не говорят. " }, { text: "Это вопрос к совету", options: { bold: true } }], 15);
  h.foot(s, [REF.abbr, "1. " + REF.cad, "2. " + REF.esc, "3. " + REF.ag]);

  // --- 3
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: main });
  h.title(s, "При стенокардии уровень АД определяет, какой препарат станет партнёром БАБ");
  const bw2 = (W - 0.35) / 2, x2 = L + bw2 + 0.35;
  s.addText("АД выше целевого: сопутствующая АГ", { shape: S.ROUNDED_RECTANGLE, x: L, y: 1.55, w: bw2, h: 0.52, rectRadius: 0.08, fill: { color: C.accent1 }, color: C.background1, bold: true, fontSize: 15, margin: [14, 14, 0, 0], valign: "middle", isTextBox: true, objectName: "Условие: АГ" });
  s.addText("АД пониженное", { shape: S.ROUNDED_RECTANGLE, x: x2, y: 1.55, w: bw2, h: 0.52, rectRadius: 0.08, fill: { color: HX.low }, color: "35404C", bold: true, fontSize: 15, margin: [14, 14, 0, 0], valign: "middle", isTextBox: true, objectName: "Условие: пониженное АД" });
  h.text(s, "↓", { x: L + bw2 / 2 - 0.2, y: 2.1, w: 0.4, h: 0.32, fontSize: 16, color: HX.caps, align: "center" });
  h.text(s, "↓", { x: x2 + bw2 / 2 - 0.2, y: 2.1, w: 0.4, h: 0.32, fontSize: 16, color: HX.caps, align: "center" });
  h.card(s, L, 2.45, bw2, 0.62, "Результат: АГ");
  let px = L + 0.2;
  px += h.pill(s, px, 2.59, "БАБ", "bab", 13) + 0.1;
  h.text(s, "+", { x: px, y: 2.59, w: 0.2, h: 0.34, fontSize: 14, bold: true, valign: "middle" });
  h.pill(s, px + 0.28, 2.59, "ДГП-БКК", "dhp", 13);
  h.card(s, x2, 2.45, bw2, 1.22, "Результат: пониженное АД");
  const pw = h.pill(s, x2 + 0.2, 2.59, "БАБ", "bab", 13);
  h.text(s, "в низкой дозе (или не-ДГП-БКК в низкой дозе)", { x: x2 + 0.3 + pw, y: 2.59, w: bw2 - pw - 0.5, h: 0.34, fontSize: 14, bold: true, valign: "middle" });
  h.text(s, "Шаг 2: заменить на ивабрадин*, ранолазин или триметазидин; добавить к шагу 1 — если АД не снижается ниже исходного", { x: x2 + 0.2, y: 3.0, w: bw2 - 0.4, h: 0.6, fontSize: 12.5 });
  h.text(s, [
    { text: "КР ИБС 2024¹: БКК рекомендуется назначать при сочетании стабильной стенокардии с АГ", options: { bullet: true, breakLine: true } },
    { text: "КР АГ 2024², прил. Б4: при АГ и ИБС к иАПФ (БРА) + ББ при стенокардии добавляется ДГП-АК", options: { bullet: true } },
  ], { x: L, y: 3.22, w: bw2, h: 1.1, fontSize: 13, paraSpaceAfter: 6 });
  h.text(s, [{ text: "КР ИБС 2024¹, табл. ПА3-5, колонка «пониженное АД», сноска «в»", options: { bullet: true } }], { x: x2, y: 3.82, w: bw2, h: 0.4, fontSize: 13 });
  h.callout(s, L, 4.6, W, 0.95, [{ text: "Снижение АД до целевых значений — часть устранения приступов стенокардии у пациентов с АГ и ИБС¹. " }, { text: "АГ здесь не отдельная цель, а условие выбора второго антиангинального компонента", options: { bold: true } }], 15);
  h.foot(s, ["* Расхождение: ESC 2024 — ивабрадин как дополнительная терапия при ФВ ЛЖ >40% без клинической СН не рекомендован (III B); в КР МЗ РФ ивабрадин — препарат 2-й линии", "1. " + REF.cadS, "2. " + REF.agS]);
  s.addNotes("«Мы не обсуждаем БАБ + амлодипин как антигипертензивную комбинацию. При стенокардии АГ просто решает, кто будет вторым».");

  // --- 4
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: main });
  h.title(s, "Вариант А разводит по разным таблеткам препараты с разными целями: симптомы и прогноз");
  h.text(s, "Условный пациент: БАБ + ДГП-БКК — для симптомов; блокатор РААС — для профилактики ССО при АГ (ЕОК I A)¹", { x: L, y: 1.47, w: W, h: 0.32, fontSize: 13.5, color: C.accent6 });
  const c4 = [[L, 0.55], [L + 0.55, 3.05], [L + 3.6, 1.9], [L + 5.5, 1.8], [L + 7.3, 1.4], [L + 8.7, 1.45], [L + 10.15, W - 10.15]];
  ["", "Таблетка 1 (FDC)", "Таблетка 2", "Коррекция блокатора РААС (K⁺, креатинин, гипотензия, кашель)", "Брадикардия на БАБ", "Отёки на амлодипине", "Молекула и доза блокатора РААС"].forEach((t, i) => {
    if (t) h.text(s, t, { x: c4[i][0] + 0.08, y: 1.88, w: c4[i][1] - 0.12, h: 0.55, fontSize: 10.5, bold: true, color: C.accent6, valign: "bottom" });
  });
  const r4 = [
    ["А", [["БАБ", "bab"], ["ДГП-БКК", "dhp"]], [["Блокатор РААС", "raas"]], [["Меняется только таблетка 2", 1], ["Меняется FDC", 0], ["Меняется FDC", 0], ["Выбор свободный", 1]]],
    ["Б", [["БАБ", "bab"], ["Блокатор РААС", "raas"]], [["ДГП-БКК", "dhp"]], [["FDC заменяют монопрепаратом БАБ", 0], ["Меняется FDC", 0], ["Меняется таблетка 2", 1], ["Ограничен дозировками FDC", 0]]],
    ["В", [["ДГП-БКК", "dhp"], ["Блокатор РААС", "raas"]], [["БАБ", "bab"]], [["Меняется FDC", 0], ["Меняется таблетка 2", 1], ["Меняется FDC", 0], ["Ограничен дозировками FDC", 0]]],
  ];
  r4.forEach(([v, t1, t2, cells], i) => {
    const y = 2.5 + i * 0.82;
    s.addShape(S.RECTANGLE, { x: L, y, w: c4[3][0] - L, h: 0.72, fill: { color: C.background1 }, line: { type: "none" }, objectName: "Строка " + v });
    h.text(s, v, { x: L + 0.12, y, w: 0.4, h: 0.72, fontSize: 22, bold: true, color: C.accent1, valign: "middle" });
    h.capsule(s, c4[1][0] + 0.06, y + 0.19, t1);
    h.capsule(s, c4[2][0] + 0.06, y + 0.19, t2);
    cells.forEach(([t, good], j) => {
      const [cx, cw] = c4[3 + j];
      s.addShape(S.RECTANGLE, { x: cx, y, w: cw, h: 0.72, fill: { color: good ? HX.ok : HX.warn }, line: { color: C.background2, width: 1 }, objectName: "Ячейка " + v + (j + 1) });
      h.text(s, t, { x: cx + 0.08, y, w: cw - 0.14, h: 0.72, fontSize: 11.5, bold: true, color: good ? HX.okInk : HX.warnInk, valign: "middle" });
    });
  });
  s.addShape(S.RECTANGLE, { x: L, y: 5.02, w: 0.18, h: 0.18, fill: { color: HX.ok }, line: { color: HX.line, width: 0.75 }, objectName: "Легенда 1" });
  h.text(s, "таблетка FDC не меняется", { x: L + 0.26, y: 4.98, w: 3, h: 0.26, fontSize: 11, color: C.accent6, valign: "middle" });
  s.addShape(S.RECTANGLE, { x: L + 3.1, y: 5.02, w: 0.18, h: 0.18, fill: { color: HX.warn }, line: { color: HX.line, width: 0.75 }, objectName: "Легенда 2" });
  h.text(s, "FDC придётся заменить, или она ограничивает выбор", { x: L + 3.36, y: 4.98, w: 5, h: 0.26, fontSize: 11, color: C.accent6, valign: "middle" });
  h.bar(s, L, 5.45, W, 0.55, [{ text: "Клиническое рассуждение о схеме, а не результаты исследований. " }, { text: "Прямых сравнений вариантов А, Б и В нет", options: { bold: true } }], 15);
  h.foot(s, ["РААС — ренин-ангиотензин-альдостероновая система; ССО — сердечно-сосудистые осложнения", "1. " + REF.cadS + " — разделы 3.1.2.1 (устранение симптомов) и 3.1.2.2 (профилактика ССО)"]);
  s.addNotes("«Ни один вариант не идеален. Вопрос в том, какой препарат у вашего пациента корректируют чаще. Если блокатор РААС — вариант А удобнее. Если отёки на амлодипине — нет».");

  // --- 5
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: main });
  h.title(s, "Фиксация антиангинальной пары на фоне иАПФ сопровождалась уменьшением частоты приступов стенокардии");
  h.text(s, "Скибицкий и соавт., 2015¹ · открытое РКИ · n=61 · АГ + стабильная стенокардия II–III ФК + метаболический синдром · 12 недель", { x: L, y: 1.47, w: W, h: 0.32, fontSize: 14, color: C.accent6 });
  skibitskyBlock(h, s, C, 1.95);
  h.foot(s, ["1. " + REF.skib]);
  s.addNotes("Удалено из v1: Divchev 2017 и фармакоэкономика. До адборда уточнить по полному тексту молекулы в группе 2 и межгрупповой p.");

  // --- 6
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: main });
  h.title(s, "Положения для обсуждения: у какого пациента рационально фиксировать антиангинальную пару");
  const crit = [
    ["Ведущая задача. ", "ИБС подтверждена; ведущая проблема — стенокардия напряжения или её эквиваленты (одышка напряжения) с подтверждённым ишемическим генезом¹"],
    ["Нужен БАБ. ", "ЧСС выше антиангинальной цели, перенесённый ИМ или ФП"],
    ["Нужен ДГП-БКК. ", "Сопутствующая АГ¹ ³ или подозрение на вазомоторный компонент: при необходимости БАБ — сочетать с ДГП-БКК и/или нитратами¹"],
    ["Показание к паре. ", "III–IV ФК — пара сразу (КР, I C) или II ФК без контроля на монотерапии (ESC, IIa B; КР, табл. ПА3-5)¹ ²"],
    ["Дозы и переносимость. ", "Дозы подобраны на монокомпонентах и совпадают с дозировками FDC; нет значимых отёков; ЧСС в допустимом диапазоне"],
    ["Блокатор РААС. ", "Нужен по своим показаниям, и важна свобода его молекулы и дозы — или противопоказан либо не переносится"],
  ];
  const cw6 = 7.55;
  crit.forEach(([b, t], i) => {
    const y = 1.55 + i * 0.8;
    h.card(s, L, y, cw6, 0.74, "Критерий " + (i + 1));
    s.addText(String(i + 1), { shape: S.OVAL, x: L + 0.17, y: y + 0.21, w: 0.32, h: 0.32, fill: { color: C.accent1 }, color: C.background1, bold: true, fontSize: 12, align: "center", valign: "middle", margin: 0, isTextBox: true, objectName: "Номер " + (i + 1) });
    h.text(s, [{ text: b, options: { bold: true } }, { text: t }], { x: L + 0.65, y, w: cw6 - 0.85, h: 0.74, fontSize: 12.5, valign: "middle" });
  });
  const qx = L + cw6 + 0.3, qw = W - cw6 - 0.3;
  s.addShape(S.ROUNDED_RECTANGLE, { x: qx, y: 1.55, w: qw, h: 4.65, rectRadius: 0.14, fill: { color: C.accent2 }, line: { type: "none" }, objectName: "Вопросы совету" });
  h.text(s, "Вопросы совету", { x: qx + 0.3, y: 1.8, w: qw - 0.6, h: 0.4, fontSize: 17, bold: true, color: C.background1 });
  h.text(s, [
    { text: "Какие критерии лишние, каких не хватает?", options: { bullet: true, breakLine: true } },
    { text: "Какой критерий главный — без него фиксация пары не имеет смысла?", options: { bullet: true, breakLine: true } },
    { text: "Где граница между «ведущая задача — стенокардия» и «ведущая задача — АГ»?", options: { bullet: true } },
  ], { x: qx + 0.3, y: 2.35, w: qw - 0.55, h: 3.5, fontSize: 14.5, color: C.background1, paraSpaceAfter: 14 });
  h.foot(s, ["Положения выходят за пределы зарегистрированных показаний FDC бисопролол + амлодипин (АГ, замещение монокомпонентов). Материал для научной дискуссии", "1. " + REF.cadS + " · 2. " + REF.escS + " · 3. " + REF.agS]);

  // --- 7
  s = pres.addSlide({ masterName: "CONTENT", sectionTitle: main });
  h.title(s, "Фиксация антиангинальной пары не нужна, если ведущая задача — не стенокардия или пара не переносится");
  const nw = 7.6;
  h.text(s, "КОГДА НЕ ВАРИАНТ А", { x: L, y: 1.5, w: nw, h: 0.3, fontSize: 12.5, bold: true, color: C.accent1, charSpacing: 1 });
  const notA = [
    ["АГ без стенокардии и её эквивалентов", " → FDC с блокатором РААС по КР АГ 2024³", 0.46],
    ["Контроль и приверженность на свободной комбинации достигнуты", " → перевод не обязателен³", 0.6],
    ["Антиангинальная цель достигается только при ЧСС <60", " → ограничение инструкции FDC (ЧСС <60 — противопоказание)", 0.6],
    ["ХСН со сниженной ФВ, декомпенсация, неишемическая ХСН III–IV ФК NYHA", "", 0.46],
    ["Изолированная вазоспастическая стенокардия", " → БКК (ESC, I A)²; БАБ не используются¹", 0.46],
    ["Значимые отёки на амлодипине", "", 0.46],
    ["Дозы вне дозировок FDC", " (например, бисопролол 2,5 или 7,5 мг)", 0.46],
    ["Нестабильная стенокардия; обструкция выносящего тракта ЛЖ", "", 0.46],
  ];
  let ny = 1.85;
  notA.forEach(([b, t, hh], i) => {
    h.card(s, L, ny, nw, hh, "Не А " + (i + 1));
    h.text(s, "×", { x: L + 0.14, y: ny, w: 0.3, h: hh, fontSize: 16, bold: true, color: HX.red, valign: "middle" });
    h.text(s, [{ text: b, options: { bold: true } }, { text: t }], { x: L + 0.48, y: ny, w: nw - 0.65, h: hh, fontSize: 12.5, valign: "middle" });
    ny += hh + 0.07;
  });
  const ux = L + nw + 0.3, uw = W - nw - 0.3;
  s.addShape(S.ROUNDED_RECTANGLE, { x: ux, y: 1.85, w: uw, h: 3.3, rectRadius: 0.12, fill: { color: HX.warn }, line: { type: "none" }, objectName: "Чего мы не знаем" });
  h.text(s, "Чего мы не знаем", { x: ux + 0.28, y: 2.05, w: uw - 0.5, h: 0.35, fontSize: 15, bold: true, color: HX.warnInk });
  h.text(s, [
    { text: "Прямых сравнений вариантов фиксации А, Б и В нет", options: { breakLine: true } },
    { text: "Влияет ли способ фиксации на приверженность антиангинальной терапии и частоту приступов, не изучено", options: { breakLine: true } },
    { text: "Как трактовать ограничение по ЧСС при антиангинальной цели 55–60 уд/мин" },
  ], { x: ux + 0.28, y: 2.5, w: uw - 0.5, h: 2.5, fontSize: 13.5, paraSpaceAfter: 10 });
  h.foot(s, ["1. " + REF.cadS + " · 2. " + REF.escS + " · 3. " + REF.agS]);
  s.addNotes("«Этот слайд важнее предыдущего. Если пациент — гипертоник без стенокардии, разговора о варианте А нет».");

  // --- Бэкап 1
  pres.addSection({ title: back });
  s = pres.addSlide({ masterName: "BACKUP", sectionTitle: back });
  h.title(s, "Инструкция FDC бисопролол + амлодипин: показание — АГ, антиангинальная фармакология описана");
  const q = [
    ["4.1 · Показания", "«артериальная гипертензия: замещение терапии монокомпонентными препаратами амлодипина и бисопролола в тех же дозах»"],
    ["4.3 · Противопоказания", "«выраженная брадикардия (частота сердечных сокращений (ЧСС) менее 60 ударов/мин)»"],
    ["4.5 · Взаимодействия", "«У пациентов со стабильной стенокардией амлодипин можно комбинировать с другими антиангинальными средствами, например, с нитратами пролонгированного или короткого действия, бета-адреноблокаторами»"],
    ["5.1 · Фармакодинамика", "«Данный лекарственный препарат обладает выраженными антигипертензивным и антиангинальным эффектами благодаря взаимодополняющему действию двух активных ингредиентов»"],
  ];
  const qw2 = (W - 0.25) / 2;
  q.forEach(([src, body], i) => {
    const x = L + (i % 2) * (qw2 + 0.25), y = 1.55 + Math.floor(i / 2) * 1.75;
    h.card(s, x, y, qw2, 1.6, "Цитата " + src);
    h.topBar(s, x, y, qw2, "Цитата — верх");
    h.text(s, src, { x: x + 0.22, y: y + 0.2, w: qw2 - 0.4, h: 0.25, fontSize: 11.5, bold: true, color: C.accent1 });
    h.text(s, body, { x: x + 0.22, y: y + 0.48, w: qw2 - 0.4, h: 1.05, fontSize: 13.5 });
  });
  h.bar(s, L, 5.15, W, 0.52, [{ text: "Раздел 5.1 описывает фармакологию и " }, { text: "не расширяет показания", options: { bold: true } }], 15);
  h.foot(s, ["ОХЛП Конкор® АМ (бисопролол + амлодипин), ЛП-№(012650)-(РГ-RU) от 28.11.2025"]);
  s.addNotes("Слайд называет продукт — противоречит решению «без бренда» для основной деки. Показывать только по вопросу из зала; решение по использованию за Евгением.");

  // --- Бэкап 2
  s = pres.addSlide({ masterName: "BACKUP", sectionTitle: back });
  h.title(s, "Добавление БКК к БАБ уменьшало частоту приступов в метаанализе дополнительной антиангинальной терапии");
  h.text(s, "Belsey et al., 2015¹ · систематический обзор и метаанализ РКИ · 46 исследований · стабильная стенокардия без контроля на монотерапии", { x: L, y: 1.47, w: W, h: 0.32, fontSize: 13.5, color: C.accent6 });
  const th = { bold: true, fontSize: 12, color: C.accent6, fill: { color: C.background1 } };
  const td = { fontSize: 12.5, color: C.text1, fill: { color: C.background1 } };
  s.addTable([
    [{ text: "Схема", options: th }, { text: "Частота приступов", options: th }, { text: "Время до приступа на нагрузке", options: th }, { text: "Время до депрессии ST", options: th }],
    [{ text: "БАБ → + БКК", options: { ...td, bold: true } }, { text: "относительное снижение 0,21 (p=0,002)", options: td }, { text: "SMD 0,30 (p<0,0001)", options: td }, { text: "незначимо", options: td }],
    [{ text: "БАБ → + ивабрадин (1 исследование)", options: td }, { text: "незначимо", options: td }, { text: "SMD 0,18 (p<0,0001)", options: td }, { text: "SMD 0,17 (p<0,0001)", options: td }],
  ], { x: L, y: 2.15, w: W, colW: [3.6, 3.5, 2.4, 2.233], rowH: 0.48, border: { type: "solid", pt: 0.75, color: HX.line }, margin: 0.1, valign: "middle", objectName: "Belsey — таблица" });
  h.bar(s, L, 4.15, W, 0.72, [{ text: "Анализ на уровне классов: БКК не только дигидропиридиновые, молекулы не выделены. Размеры эффекта скромные. Финансирование — A. Menarini" }], 14);
  h.foot(s, ["SMD — стандартизированная разность средних", "1. " + REF.belsey]);

  const file = path.join(OUT, "2026-10-20_adboard-fdc-bab-amlo_v2-draft.pptx");
  await pres.writeFile({ fileName: file });
  await applyTheme(file, THEME);
  return file;
}

(async () => {
  console.log(await buildV1());
  console.log(await buildV2());
})().catch(e => { console.error(e); process.exit(1); });
