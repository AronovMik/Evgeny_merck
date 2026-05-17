# 2026-05-17 — Настройка репозитория и перенос первого чата

## Контекст
Начали с пустого репозитория. Цель — структурировать постоянную рабочую среду для Евгения (Federal Medical Advisor Cardiology, Merck Russia) под портфель Конкор + смежные задачи.

## Что сделано
- Создана базовая структура репозитория: `tasks/`, `context/`, `archive/claude-chats/`, `templates/`.
- В корне положены `INSTRUCTIONS.md` (правила v2.0 дословно), `CLAUDE.md` (контекст для агента), `README.md` (навигация), `.gitignore`.
- Уточнено: Конкор НСТ = бисопролол + гидрохлортиазид 6,25 мг.
- Уточнено: инструкции v2.0 сохраняются дословно (включая упоминания канаглифлозина/SGLT2), так как используются и для других задач Евгения.
- Перенесён первый чат из claude.ai: `archive/claude-chats/2026-03_klinicheskie-sluchai-konkor.md` — рецензирование клинических случаев под Конкор АМ + анализ постов Telegram-канала.
- По запросу Евгения внедрена система логирования: `STATE.md`, `TODO.md`, `journal/`, `ideas/INBOX.md`, `decisions/`. Соответствующее решение зафиксировано в `decisions/2026-05-17_logging-structure.md`.
- В `CLAUDE.md` добавлено правило: при рецензировании всегда явно фиксировать рамку гайдлайнов (КР МЗ РФ / ESC / ESH / иные); при расхождениях между гайдлайнами — указывать явно.

## Решения
- Структура «по типам задач + контекст» одобрена Евгением (см. `decisions/2026-05-17_repo-structure.md`).
- Система логирования с тремя уровнями (STATE → TODO → journal) + ideas + decisions (см. `decisions/2026-05-17_logging-structure.md`).
- Год перенесённого чата — 2026, не 2025.

## Что осталось / следующий шаг
- Дождаться следующих чатов из claude.ai и перенести их в `archive/claude-chats/`.
- При первой реальной задаче — создать файл в соответствующей подпапке `tasks/`.

## Затронутые файлы
- `INSTRUCTIONS.md`, `CLAUDE.md`, `README.md`, `STATE.md`, `TODO.md`, `.gitignore`
- `archive/claude-chats/README.md`, `archive/claude-chats/2026-03_klinicheskie-sluchai-konkor.md`
- `tasks/*/README.md`, `context/*/README.md`, `templates/README.md`
- `journal/README.md`, `ideas/INBOX.md`, `decisions/README.md`, `decisions/2026-05-17_*.md`
