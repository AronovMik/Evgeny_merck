# 2026-05-18 — Загрузка международных гайдлайнов (ESC, AHA/ACC)

## Контекст
Евгений прислал три международных guideline в формате Markdown — дополняют российские КР, загруженные накануне.

## Что сделано
- В `context/guidelines/` добавлены MD по конвенции `{организация}_{год}_{тема}.md`:
  - `ESC_2024_hypertension.md` — 2024 ESC Guidelines for the management of elevated blood pressure and hypertension (ESC, endorsed by ESE и ESO).
  - `ESC_2024_CCS.md` — 2024 ESC Guidelines for the management of chronic coronary syndromes (ESC, endorsed by EACTS).
  - `ACC-AHA_2023_chronic-coronary-disease.md` — 2023 AHA/ACC/ACCP/ASPC/NLA/PCNA Guideline for the Management of Patients With Chronic Coronary Disease.
- `context/guidelines/INDEX.md`: заполнена секция «ESC / ESH / AHA / ACC».
- `STATE.md` и `TODO.md` обновлены.

## Решения
- Файлы хранятся as-is в MD (раньше уже выгружали — отдельных конспектов пока не делаем).
- Префикс `ACC-AHA` (через дефис) использован для документа, выпущенного совместно несколькими организациями; через дефис, чтобы не путать с подчёркиванием разделителем полей в конвенции.

## Что осталось / следующий шаг
- При необходимости — короткие summary по бисопрололу/Конкору для каждого нового guideline.
- Дозагрузить ESC 2023 HF и КР МЗ РФ по ФП/НЖТ 2025.

## Затронутые файлы
- `context/guidelines/ESC_2024_hypertension.md` (новый)
- `context/guidelines/ESC_2024_CCS.md` (новый)
- `context/guidelines/ACC-AHA_2023_chronic-coronary-disease.md` (новый)
- `context/guidelines/INDEX.md`, `STATE.md`, `TODO.md`
