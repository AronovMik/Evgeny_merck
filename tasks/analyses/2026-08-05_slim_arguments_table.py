#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Уровень 1: удаление целых блоков из arguments_table.md.
Никакого пересказа. Только:
  (a) удаление блоков целиком,
  (b) перенос двух библиографических ссылок из «Статус» в «Источник» ДОСЛОВНО,
  (c) точечное удаление ссылок на conflicts_log (файл в базу знаний не загружен).
"""
import re, sys

SRC = 'simulator/arguments_table.md'
OUT = 'simulator/arguments_table.md'

t = open(SRC, encoding='utf-8').read()
orig = t

# ---------------------------------------------------------------- утилиты
LABEL = re.compile(r'(?m)^\*\*')
STOP  = re.compile(r'(?m)^(\*\*|---\s*$|## )')

def block_span(text, start):
    """Границы блока: от заголовка до следующего верхнеуровневого маркера."""
    m = STOP.search(text, start + 2)
    return (start, m.start() if m else len(text))

def drop_block(text, header_re):
    """Удалить блок(и), начинающиеся с header_re."""
    while True:
        m = re.search(header_re, text)
        if not m:
            return text
        a, b = block_span(text, m.start())
        text = text[:a] + text[b:]

def split_cards(text):
    """(шапка, [карточки], хвост-журнал)"""
    i = text.index('\n## Аргумент 1 ')
    head = text[:i+1]
    rest = text[i+1:]
    j = rest.find('\n## Журнал изменений')
    tail = rest[j:] if j >= 0 else ''
    body = rest[:j] if j >= 0 else rest
    cards = re.split(r'(?m)(?=^## Аргумент )', body)
    cards = [c for c in cards if c.strip()]
    return head, cards, tail

head, cards, tail = split_cards(t)
report = []

# ---------------------------------------------------- 1. журнал изменений
report.append(('Журнал изменений (хвост файла)', len(tail)))
tail = ''

# ------------------------------------------------------------ 2. карточки
NO_NOTES = {2, 3, 4, 5, 6, 9}          # «Замечания/флаги» удалить целиком
KEEP_NOTES_15 = 15                      # оставить только связки с 7, 16, 21

# Дословные ссылки, которые сидят внутри «Статус» и больше нигде в карточке нет
STATUS_TO_SOURCE = {
 21: '**Источник:** PACE Investigators. Lancet Respir Med. 2026. '
     'doi:10.1016/S2213-2600(25)00390-X.\n',
 22: '**Источник:** Verma AA, Khuu W, Tadrous M, Gomes T, Mamdani MM. '
     '*Fixed-dose combination antihypertensive medications, adherence, and clinical '
     'outcomes: a population-based retrospective cohort study.* '
     'PLOS Medicine 2018;15(6):e1002584. DOI:10.1371/journal.pmed.1002584.\n',
}

# Ссылки, которые в FULL лежат ТОЛЬКО внутри удаляемого блока «Источник в PPTX Мерк».
# Переносятся дословно в «Источник (первичный)» той же карточки.
RESCUE_SOURCE = {
 5: '- Первоисточники цифр приверженности (цитируются через PPTX Мерк В.3; сами публикации '
    'в корпусе не загружены):\n'
    '  - Hostalek U., Czarnecka D. et al. *Efficacy of and Adherence to a Fixed-dose Combination '
    'of Bisoprolol and Amlodipine in Hypertensive Patients with and without Type 2 Diabetes '
    'Mellitus or Coronary Artery Disease.* J Heart Health 1(4). '
    'doi: http://dx.doi.org/10.16966/2379-769X.114\n'
    '  - Hostalek U. *Treatment of hypertension with a fixed-dose combination of bisoprolol '
    'and amlodipine in daily practice: results of a multinational non-investigational study.* '
    'Cardiovasc Disord Med. 2016;1(3):1–5. doi: 10.15761/CDM.1000118\n',
}

new_cards = []
for c in cards:
    num = int(re.match(r'## Аргумент (\d+)', c).group(1))
    before = len(c)

    # --- спасение ссылок из блока, который будет удалён
    if num in RESCUE_SOURCE:
        m = re.search(r'(?m)^\*\*Источник \(первичный\):\*\*', c)
        assert m, f'Арг {num}: не найден блок «Источник (первичный)»'
        a, b = block_span(c, m.start())
        c = c[:b].rstrip('\n') + '\n' + RESCUE_SOURCE[num] + '\n' + c[b:]

    # --- Статус
    m = re.search(r'(?m)^\*\*Статус:\*\*', c)
    if m:
        a, b = block_span(c, m.start())
        c = c[:a] + (STATUS_TO_SOURCE.get(num, '') and STATUS_TO_SOURCE[num] + '\n') + c[b:]

    # --- Источник в PPTX Мерк
    c = drop_block(c, r'(?m)^\*\*Источник в PPTX Мерк')

    # --- Замечания/флаги
    if num in NO_NOTES:
        c = drop_block(c, r'(?m)^\*\*Замечания/флаги:\*\*')
    elif num == KEEP_NOTES_15:
        m = re.search(r'(?m)^\*\*Замечания/флаги:\*\*', c)
        a, b = block_span(c, m.start())
        blk = c[a:b]
        bullets = re.findall(r'(?m)^- .*(?:\n(?!- |\*\*|---|## ).*)*', blk)
        keep = [x for x in bullets if re.search(r'Связка с аргументом (7|16|21)', x)]
        assert len(keep) == 3, f'Арг 15: ожидалось 3 связки, найдено {len(keep)}'
        c = c[:a] + '**Замечания/флаги:**\n' + '\n'.join(k.rstrip() for k in keep) + '\n\n' + c[b:]

    report.append((f'Аргумент {num}', before - len(c)))
    new_cards.append(c)

cards = new_cards

# ------------------------------------------- 3. ссылки на conflicts_log
EDITS = [
 # шапка: conflicts_log в базу не загружен
 ('Всё, что не удалось подтвердить, вынесено в `conflicts_log.md`.',
  'Всё, что не удалось подтвердить, в эту таблицу не включено.'),
 # Арг 4, «Численные данные» — вывод остаётся, указатель уходит
 ('расхождение зафиксировано в `conflicts_log.md` Н5, цифра PPTX остаётся неподтверждённой',
  'цифра PPTX остаётся неподтверждённой'),
 # Арг 4, «Границы применимости» — вместо указателя сам вывод
 ('это расхождение источников, см. `conflicts_log.md` Н5.',
  'это расхождение источников; каноническая цифра проекта — 34% (решение куратора 2026-08-02).'),
 # Арг 5, «Численные данные» — запрет уже стоит в «Границах» той же карточки
 ('в загруженных документах по-прежнему **не найдена** — см. `conflicts_log.md` Н2.',
  'в загруженных документах **не найдена**.'),
 # Арг 13, «Замечания/флаги»
 ('в основном тексте не найдены. См. `conflicts_log.md`.',
  'в основном тексте не найдены.'),
 # Арг 14, «Замечания/флаги» — буллет целиком аудиторский
 ('- Н7 в `conflicts_log.md` — **закрыто** 2026-04-18 (первоисточник предоставлен куратором)\n',
  ''),
 # Арг 20, «Границы применимости»
 ('(Н2 в `conflicts_log.md`)', ''),
]

# ------------------------------------------------- 4. строка в шапку
head = head.replace(
 'Источники: КР МЗ РФ',
 '**В таблице только проверенные аргументы.** Каждая карточка сверена с первоисточником, '
 'корпоративным материалом Мерк или клинической рекомендацией; непроверенное в таблицу '
 'не включается. Отдельная пометка о статусе верификации в карточках не приводится — '
 'она была бы одинаковой для всех.\n\nИсточники: КР МЗ РФ', 1)

out = head + ''.join(cards) + tail
for a, b in EDITS:
    n = out.count(a)
    if n != 1:
        sys.exit(f'ОШИБКА: правка встретилась {n} раз, ожидалась 1:\n  {a[:90]}')
    out = out.replace(a, b)

# ------------------------------------------------- 5. косметика пробелов
out = re.sub(r'\n{4,}', '\n\n\n', out)
out = re.sub(r'(?m)^ +$', '', out)
out = re.sub(r'---\s*\n\s*---', '---', out)          # сдвоенный разделитель после удалённого блока

open(OUT, 'w', encoding='utf-8').write(out)

print(f'{"было":>10}: {len(orig):>7d} знаков')
print(f'{"стало":>10}: {len(out):>7d} знаков')
print(f'{"убрано":>10}: {len(orig)-len(out):>7d} знаков ({(len(orig)-len(out))/len(orig)*100:.1f}%)\n')
for name, d in report:
    if d: print(f'  {name:<34s} −{d:>6d}')
