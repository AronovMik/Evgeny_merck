# INDEX — клинические рекомендации

> Короткий перечень всего, что лежит в `context/guidelines/`. Обновляется при добавлении/удалении документов.

## КР МЗ РФ / РКО

| Файл | Тема | Год | Источник |
|---|---|---|---|
| [`RKO_2024_hypertension.pdf`](./RKO_2024_hypertension.pdf) | Артериальная гипертензия у взрослых | 2024 | РКО, одобрено НПС МЗ РФ 12.09.2024; doi: 10.15829/1560-4071-2024-6117 |
| [`RKO_2024_stable-CAD.pdf`](./RKO_2024_stable-CAD.pdf) | Стабильная ишемическая болезнь сердца | 2024 | РКО, одобрено НПС МЗ РФ 12.09.2024; doi: 10.15829/1560-4071-2024-6110 |
| [`RKO_2024_chronic-HF.pdf`](./RKO_2024_chronic-HF.pdf) | Хроническая сердечная недостаточность | 2024 | РКО, одобрено НПС МЗ РФ 12.09.2024; doi: 10.15829/1560-4071-2024-6162 |
| [`RKO_2025_atrial-fibrillation-flutter.md`](./RKO_2025_atrial-fibrillation-flutter.md) | Фибрилляция и трепетание предсердий | 2025 | КР МЗ РФ |
| [`RKO_2023_lipid-disorders.pdf`](./RKO_2023_lipid-disorders.pdf) | Нарушения липидного обмена | 2023 | РКО, одобрено НПС МЗ РФ 27.12.2022; doi: 10.15829/1560-4071-2023-5471 |

## ESC / ESH / AHA / ACC

### Артериальная гипертензия и ИБС

| Файл | Тема | Год | Источник |
|---|---|---|---|
| [`ESC_2024_hypertension.md`](./ESC_2024_hypertension.md) | Elevated blood pressure and hypertension | 2024 | ESC, endorsed by ESE и ESO |
| [`ESC_2024_CCS.md`](./ESC_2024_CCS.md) | Chronic coronary syndromes | 2024 | ESC, endorsed by EACTS |
| [`ACC-AHA_2023_chronic-coronary-disease.md`](./ACC-AHA_2023_chronic-coronary-disease.md) | Chronic coronary disease | 2023 | AHA/ACC/ACCP/ASPC/NLA/PCNA |

### Дислипидемия

| Файл | Тема | Год | Источник |
|---|---|---|---|
| [`ACC-AHA_2026_dyslipidemia.md`](./ACC-AHA_2026_dyslipidemia.md) | Управление дислипидемией | 2026 | ACC/AHA/AACVPR/ABC/ACPM/ADA/AGS/APhA/ASPC/NLA/PCNA; J Am Coll Cardiol. 2026;87(19):2624–2757; doi: 10.1016/j.jacc.2025.11.016; copublished in Circulation |
| [`KDIGO_2013_lipids-in-CKD.pdf`](./KDIGO_2013_lipids-in-CKD.pdf) | Lipid Management in Chronic Kidney Disease | 2013 | KDIGO (Kidney Disease: Improving Global Outcomes); Kidney Int Suppl 2013;3(3):259–305. **Внимание: редакция 2013, частично устаревшая** (есть более поздние KDIGO-документы по липидам/ХБП; при работе сверять); см. Table 4 — рекомендованные дозы статинов при ХБП G3a–G5 |

### Сердечная недостаточность

| Файл | Тема | Год | Источник |
|---|---|---|---|
| [`ESC_2021_HF.md`](./ESC_2021_HF.md) | Diagnosis and treatment of acute and chronic heart failure | 2021 | ESC, с участием HFA; основная рамка для ESC-линии по СН |
| [`ESC_2023_HF-focused-update.md`](./ESC_2023_HF-focused-update.md) | Focused update of the 2021 ESC Guidelines on HF | 2023 | ESC, с участием HFA; обновление по СН2023 (SGLT2 при ВНФВ/СНсФВ, новые исходы) |
| [`ACC-AHA_2022_HF.md`](./ACC-AHA_2022_HF.md) | Management of Heart Failure | 2022 | AHA/ACC/HFSA Joint Committee; J Am Coll Cardiol. 2022 |
| [`ACC_2023_HFpEF-consensus.md`](./ACC_2023_HFpEF-consensus.md) | Expert Consensus Decision Pathway on Management of HFpEF | 2023 | ACC Expert Consensus; J Am Coll Cardiol. 2023 |
| [`ASE_2025_HFpEF-diagnosis.md`](./ASE_2025_HFpEF-diagnosis.md) | HFpEF Diagnosis — Update from the American Society of Echocardiography | 2025 | ASE Guidelines and Standards; обновление по эхокардиографической диагностике СНсФВ |

---

**Конвенция файлов:** `{организация}_{год}_{тема}.{ext}`. Рядом по желанию класть `{организация}_{год}_{тема}_summary.md` — краткий конспект ключевых положений по бисопрололу/портфелю.

## Рамка использования

В любых задачах **основная рамка — КР МЗ РФ** (см. `CLAUDE.md`, Правило 5). ESC/ESH/AHA/ACC и другие зарубежные гайдлайны привлекаются:

1. Когда КР МЗ РФ не дают позиции по конкретному вопросу.
2. Когда формулировки расходятся — обе позиции приводятся **с явной маркировкой источника** на слайде / в тексте.
3. Когда зарубежный документ содержит свежие данные / новые подходы, ещё не отражённые в КР МЗ РФ (пример: ACC/AHA 2026 по дислипидемии — новые CAC-бины 0 / 1–9 / 10–99 / 100–299 / 300–999 / ≥1000 и дифференцированные цели ЛНП по баллу CAC).

Расхождения **не разрешаются «в пользу одного победителя»** без явного запроса Евгения — обе позиции остаются с указанием источника.
