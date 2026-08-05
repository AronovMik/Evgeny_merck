#!/usr/bin/env bash
# Запуск песочницы одной командой: ./sandbox/run.sh
cd "$(dirname "$0")/.." || exit 1
if [ ! -f sandbox/.env ]; then
  echo "Нет sandbox/.env — работаю в mock-режиме (запросы к API не уходят)."
  echo "Чтобы подключить модель: cp sandbox/.env.example sandbox/.env и вписать ключ."
  echo
fi
exec python3 sandbox/app.py "$@"
