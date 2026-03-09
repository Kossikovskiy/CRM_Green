#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/var/www/crm/GCRM-2"
VENV="/var/www/crm/venv/bin/activate"

echo "[1/7] Переход в директорию проекта: ${APP_DIR}"
cd "${APP_DIR}"

echo "[2/7] Обновление кода из origin/main"
git fetch origin main
# Приводим рабочее дерево к точному состоянию origin/main
# (не затрагивает .env, если он untracked)
git reset --hard origin/main

COMMIT_SHA="$(git rev-parse --short HEAD)"
echo "Текущий commit: ${COMMIT_SHA}"

echo "[3/7] Установка прав на скрипты"
chmod +x start.sh backup.sh deploy.sh

echo "[4/7] Установка/обновление зависимостей"
source "${VENV}"
pip install -r requirements.txt

echo "[5/7] Перезапуск сервисов"
systemctl restart crm
systemctl restart greencrm-bot

echo "[6/7] Проверка статуса сервисов"
systemctl is-active --quiet crm || { echo "❌ crm не запустился"; systemctl status crm --no-pager -n 80; exit 1; }
systemctl is-active --quiet greencrm-bot || { echo "❌ greencrm-bot не запустился"; systemctl status greencrm-bot --no-pager -n 80; exit 1; }

echo "[7/7] Готово"
echo "✅ Деплой завершен. commit=${COMMIT_SHA}"
