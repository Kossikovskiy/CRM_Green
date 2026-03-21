#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/var/www/crm/GCRM-2"
VENV="/var/www/crm/venv/bin/activate"

echo "[1/8] Переход в директорию проекта: ${APP_DIR}"
cd "${APP_DIR}"

echo "[2/8] Обновление кода из origin/main"
git fetch origin main
# Приводим рабочее дерево к точному состоянию origin/main
# (не затрагивает .env, если он untracked)
git reset --hard origin/main

COMMIT_SHA="$(git rev-parse --short HEAD)"
echo "Текущий commit: ${COMMIT_SHA}"

echo "[3/8] Установка прав на скрипты"
chmod +x start.sh backup.sh deploy.sh

echo "[4/8] Обновление systemd-файлов"
SYSTEMD_SRC="${APP_DIR}/etc/systemd/system"
if [ -d "${SYSTEMD_SRC}" ]; then
    cp "${SYSTEMD_SRC}"/*.service /etc/systemd/system/ 2>/dev/null || true
    cp "${SYSTEMD_SRC}"/*.timer   /etc/systemd/system/ 2>/dev/null || true
    systemctl daemon-reload
    echo "    ✅ systemd-файлы обновлены"
else
    echo "    ⏭️  папка ${SYSTEMD_SRC} не найдена, пропускаем"
fi

echo "[5/8] Установка/обновление зависимостей"
source "${VENV}"
pip install -r requirements.txt

echo "[6/8] Перезапуск сервисов"
systemctl restart crm
systemctl restart greencrm-bot

echo "[7/8] Проверка статуса сервисов"
systemctl is-active --quiet crm || { echo "❌ crm не запустился"; systemctl status crm --no-pager -n 80; exit 1; }
systemctl is-active --quiet greencrm-bot || { echo "❌ greencrm-bot не запустился"; systemctl status greencrm-bot --no-pager -n 80; exit 1; }

echo "[8/8] Готово"
echo "✅ Деплой завершен. commit=${COMMIT_SHA}"
