#!/usr/bin/env bash
# Запись ключа API в sandbox/.env.
# Запуск:  bash sandbox/set-key.sh
#
# Ключ вводится скрыто (на экране не появится) и никуда, кроме sandbox/.env,
# не попадает. Файл в .gitignore — в репозиторий не уедет.

set -u

cd "$(dirname "$0")/.." || exit 1
ENV_FILE="sandbox/.env"

printf 'Вставьте ключ API и нажмите Enter (ввод не отображается): '
read -rs KEY
printf '\n'

if [ -z "${KEY}" ]; then
  echo "Ключ пустой — ничего не записано."
  exit 1
fi

# Пробелы по краям — частый результат копирования, снимаем молча.
KEY="$(printf '%s' "$KEY" | tr -d '[:space:]')"

case "$KEY" in
  sk-*) ;;
  *) echo "Замечание: ключ не начинается на sk-. Для OpenAI это необычно;"
     echo "           для корпоративного шлюза (Langdock) — нормально. Записываю как есть." ;;
esac

if [ ! -f "$ENV_FILE" ]; then
  cp sandbox/.env.example "$ENV_FILE" 2>/dev/null || : > "$ENV_FILE"
fi

# Существующие настройки сохраняем, меняем только строку с ключом.
TMP="$(mktemp)"
grep -v '^OPENAI_API_KEY=' "$ENV_FILE" > "$TMP" 2>/dev/null || : > "$TMP"
{ printf 'OPENAI_API_KEY=%s\n' "$KEY"; cat "$TMP"; } > "$ENV_FILE"
rm -f "$TMP"
unset KEY
chmod 600 "$ENV_FILE" 2>/dev/null || true

echo "Готово. Ключ записан в $ENV_FILE (доступ только владельцу)."
echo
echo "Запуск песочницы:  python3 sandbox/app.py"
