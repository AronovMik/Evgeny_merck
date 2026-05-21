# 2026-05-21 — Полный пакет международных гайдлайнов по сердечной недостаточности

## Контекст
Евгений прислал 5 MD-файлов гайдлайнов по СН с явной просьбой «запушь в main». По модели «main = курируемая библиотека» это разрешённый сценарий: пользователь явно указывает, что контент библиотечный.

## Что сделано
- В `context/guidelines/` добавлены 5 документов по конвенции `{организация}_{год}_{тема}.md`:
  - `ESC_2021_HF.md` — 2021 ESC Guidelines for the diagnosis and treatment of acute and chronic heart failure (основная рамка ESC по СН).
  - `ESC_2023_HF-focused-update.md` — 2023 Focused Update of the 2021 ESC HF Guidelines (SGLT2 при ВНФВ/СНсФВ, новые данные).
  - `ACC-AHA_2022_HF.md` — 2022 AHA/ACC/HFSA Guideline for the Management of Heart Failure.
  - `ACC_2023_HFpEF-consensus.md` — 2023 ACC Expert Consensus Decision Pathway on Management of HFpEF.
  - `ASE_2025_HFpEF-diagnosis.md` — 2025 HFpEF Diagnosis: Update from the American Society of Echocardiography.

- `context/guidelines/INDEX.md` **перегруппирован**: вместо одного списка «ESC/ESH/AHA/ACC» введены подразделы по терапевтическим областям — «Артериальная гипертензия и ИБС», «Дислипидемия», «Сердечная недостаточность». Это облегчает навигацию по мере роста библиотеки.

- `STATE.md`, `TODO.md` обновлены.

## Решения
- **Группировка INDEX по областям**, а не по организациям. С добавлением 5 файлов по СН плоский список «ESC/ESH/AHA/ACC» становился неудобным; разделение по болезни делает быстрее поиск релевантного гайдлайна под задачу.
- **Имя `ASE_` для документа 2025 года**, а не `ACC_`: документ помечен «ACC HFpEF Diagnosis», но в самом тексте идентифицирован как «Update From the American Society of Echocardiography» — публикация ASE. Сохранил происхождение в имени.
- **«ESC 2023 HF focused update»**, а не «ESC 2023 HF» — это focused update к 2021, не самостоятельный гайдлайн.

## Что осталось
- При появлении новой редакции КР МЗ РФ по ХСН (после 2024) — добавлять рядом, старую не удалять.
- Если Евгений захочет короткие summary под бисопролол по каждому из этих документов — отдельной задачей.

## Затронутые файлы
- `context/guidelines/ESC_2021_HF.md` (новый)
- `context/guidelines/ESC_2023_HF-focused-update.md` (новый)
- `context/guidelines/ACC-AHA_2022_HF.md` (новый)
- `context/guidelines/ACC_2023_HFpEF-consensus.md` (новый)
- `context/guidelines/ASE_2025_HFpEF-diagnosis.md` (новый)
- `context/guidelines/INDEX.md` (перегруппирован)
- `STATE.md`, `TODO.md`
