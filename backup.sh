#!/bin/bash
# Скрипт для создания резервных копий базы данных PostgreSQL
# v1.1 — добавлена загрузка в Yandex Object Storage (S3)

set -e

# --- НАСТРОЙКИ ---
BACKUP_DIR="/var/www/crm/GCRM-2/backups"
RETENTION_DAYS=2
ENV_FILE="/var/www/crm/GCRM-2/.env"

# --- S3 НАСТРОЙКИ ---
S3_BUCKET="5485cfd5-d8de-4805-ad4f-6a0097ecf18d"
S3_ENDPOINT="https://s3.twcstorage.ru"
S3_ACCESS_KEY="3Z2B7NY0PVID9PI6QDKM"
S3_SECRET_KEY="ORqVAuuH44YuIZCggU5lRRENWcaWMDkGKkVszGTk"
S3_RETENTION_DAYS=30

# --- ЛОГИКА СКРИПТА ---

echo "---"
echo "Запуск процесса резервного копирования: $(date)"

# Загружаем .env
if [ -f "$ENV_FILE" ]; then
    echo "... Загружаю переменные из $ENV_FILE ..."
    export $(cat "$ENV_FILE" | grep -v '#' | xargs)
else
    echo "⚠️  Предупреждение: Файл .env не найден в $ENV_FILE" >&2
fi

if [ -z "$DATABASE_URL" ]; then
    echo "❌ Ошибка: DATABASE_URL не установлена. Выход." >&2
    exit 1
fi

# Создаём дамп
DATE_STAMP=$(date +"%Y-%m-%d_%H-%M")
FILE_NAME="backup-$DATE_STAMP.sql.gz"
FULL_PATH="$BACKUP_DIR/$FILE_NAME"

echo "📄 Имя файла: $FILE_NAME"
echo "⏳ Создаю дамп базы данных..."
pg_dump --dbname="$DATABASE_URL" -Fc | gzip > "$FULL_PATH"
echo "✅ Резервная копия создана: $FULL_PATH"

# Загружаем в S3
echo "☁️  Загружаю в Yandex Object Storage..."
if command -v aws &> /dev/null; then
    AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
    AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
    aws s3 cp "$FULL_PATH" "s3://$S3_BUCKET/backups/$FILE_NAME" \
        --endpoint-url "$S3_ENDPOINT" \
        --no-progress \
        --quiet
    echo "✅ Загружено в S3: s3://$S3_BUCKET/backups/$FILE_NAME"

    # Удаляем старые бэкапы из S3 (старше 30 дней)
    echo "🧹 Удаляю старые бэкапы из S3 (старше $S3_RETENTION_DAYS дней)..."
    CUTOFF_DATE=$(date -d "$S3_RETENTION_DAYS days ago" +%Y-%m-%d)
    AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
    AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
    aws s3 ls "s3://$S3_BUCKET/backups/" \
        --endpoint-url "$S3_ENDPOINT" | \
    awk '{print $4}' | \
    while read -r fname; do
        fdate=$(echo "$fname" | grep -oP '\d{4}-\d{2}-\d{2}')
        if [[ "$fdate" < "$CUTOFF_DATE" ]]; then
            AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" \
            AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" \
            aws s3 rm "s3://$S3_BUCKET/backups/$fname" \
                --endpoint-url "$S3_ENDPOINT" --quiet
            echo "   Удалён: $fname"
        fi
    done
    echo "✅ Очистка S3 завершена."
else
    echo "⚠️  aws CLI не установлен — пропускаю загрузку в S3"
fi

# Удаляем старые локальные бэкапы
echo "🧹 Удаляю старые локальные бэкапы (старше $RETENTION_DAYS дней)..."
find "$BACKUP_DIR" -type f -name "*.sql.gz" -mtime +$(($RETENTION_DAYS - 1)) -print -delete
echo "✅ Локальная очистка завершена."
echo "---"
