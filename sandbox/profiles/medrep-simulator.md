---
name: Тренажёр Конкор — как проект в Langdock
order: 0
description: Промпт medrep_prompt_v16.md в поле инструкций + 7 файлов проекта. Их всего 7, то есть меньше 20, поэтому по правилу Langdock они подаются модели ЦЕЛИКОМ, а не поиском по фрагментам. Если в Langdock файлы подключены базой знаний или синхронизированной папкой — поставьте knowledge_mode: embedding.
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
knowledge_mode: auto
# Потолок предпросмотра на файл. Не из документации: подобран под наблюдение
# Евгения — индикатор контекста в Langdock показывает ~40 тыс. токенов на этих
# файлах, тогда как целиком они дают ~101 тыс. 20 000 символов на файл дают
# ~41 тыс. токенов, что сходится. Проверьте по своему индикатору и поправьте.
knowledge_preview_char_limit: 20000
knowledge_top_k: 50
---
