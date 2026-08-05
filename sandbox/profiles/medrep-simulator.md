---
name: Тренажёр Конкор — как проект в Langdock
order: 0
description: Промпт medrep_prompt_v16.md в поле инструкций + 7 файлов базы знаний, поданных поиском по фрагментам — та же механика, что у проектов Langdock.
model: gpt-5.5
system_files:
  - simulator/medrep_prompt_v16.md
knowledge_files:
  - simulator/typology_v2.md
  - simulator/quality_criteria.md
  - simulator/arguments_table.md
  - simulator/patient_portraits.md
  - simulator/competitive_messaging.md
  - simulator/mandatory_args.md
  - simulator/onboarding.md
knowledge_top_k: 50
---
