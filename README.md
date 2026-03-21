# GrassCRM

CRM-система для компании по покосу газонов и ландшафтным работам. Бэкенд на FastAPI, фронтенд — одностраничное приложение на чистом JS. Развёрнута на VPS под Ubuntu 24.04, данные хранятся в PostgreSQL (Supabase).

---

## Стек

| Слой | Технология |
|---|---|
| Бэкенд | Python 3.12, FastAPI, SQLAlchemy |
| Веб-сервер | Uvicorn + systemd |
| База данных | PostgreSQL (Supabase, Session Pooler) + pgvector 0.8.0 |
| Аутентификация | Auth0 (вход через Яндекс) |
| Экспорт | openpyxl (Excel), reportlab (PDF) |
| Уведомления | python-telegram-bot |
| AI | DeepSeek (`deepseek-chat`) через OpenAI-совместимый API (Timeweb Cloud AI) |
| Парсинг файлов | pdfplumber, openpyxl, python-docx |

---

## Возможности

- **Сделки** — канбан-доска с drag & drop, широкая карточка в две колонки с вкладками (Заметки / Комментарии / Файлы / AI), услуги с кастомной ценой, скидка, налог, фото до/после, дублирование сделок, учёт часов на выезд
- **Контакты** — карточка клиента с историей сделок, быстрое создание сделки из карточки контакта с предзаполненным клиентом
- **Задачи** — список с приоритетами, назначением на сотрудника и сроками
- **Расходы** — учёт по категориям с фильтром по году
- **Техника** — учёт оборудования и история ТО
- **Склад** — остатки расходных материалов
- **Прайс-лист** — услуги с единицами измерения и ценами (отдельные каталоги для покоса и электрики)
- **Налог** — расчёт налога по ставке с режимами «включён» / «сверху»
- **Аналитика** — воронка, динамика выручки/расходов, топ услуг, сезонное сравнение год к году, маржинальность по клиентам, загрузка по дням недели, статистика по рабочим часам + AI-разбор (только Admin)
- **Бюджет** — планирование по периодам с процентом исполнения (только Admin)
- **Экспорт** — отчёт в Excel (4 листа) и PDF за выбранный год
- **Заметки** — свободные текстовые записи (Google Keep-стиль)
- **Поиск по сделкам** — поиск по названию, клиенту, телефону прямо в канбане
- **Мультипроект** — поддержка двух бизнесов (покос и электрика) с раздельными каталогами и этапами
- **AI-агент** — встроен в карточку сделки, раздел «Аналитика» и раздел «Сервис»
- **Роли** — Admin видит всё, User видит только свои сделки и задачи
- **Audit Log** — журнал изменений в панели Сервис с фильтрами
- **Мониторинг** — healthcheck (`GET /api/health`), структурированные логи с ротацией, Telegram-алерты при 500 ошибках

---

## Структура проекта

```
GCRM-2/
├── main.py                  # Точка входа FastAPI (v8.0.5) — только init и роутеры
├── index.html               # Фронтенд (SPA, без фреймворков)
├── bot.py                   # Telegram-бот с отчётами и созданием сделок
├── assistant_bot.py         # Личный AI-агент владельца
├── client_bot.py            # Клиентский AI-бот (отключён, сохранён для будущего)
├── deploy.sh                # Скрипт деплоя
├── backup.sh                # Скрипт резервного копирования БД
├── start.sh                 # Запуск uvicorn для systemd
├── requirements.txt         # Зависимости Python
├── backups/                 # Дампы БД (не коммитить!)
└── app/                     # Пакет бэкенда
    ├── config.py            # Переменные окружения и константы
    ├── cache.py             # In-memory кэш
    ├── logging_setup.py     # Логгер, Telegram-алерты, HTTP middleware
    ├── models.py            # SQLAlchemy ORM-модели (22 таблицы)
    ├── database.py          # Engine, SessionFactory, get_db, seed
    ├── schemas.py           # Pydantic-схемы запросов/ответов
    ├── security.py          # Auth, роли, guard_project
    ├── migrations.py        # _ensure_* миграции и фоновые воркеры
    └── routers/
        ├── auth.py          # /api/auth/*
        ├── users.py         # /api/users/*, /api/me, /api/projects
        ├── services.py      # /api/services/*, /api/electric-services/*
        ├── contacts.py      # /api/contacts/*
        ├── tasks.py         # /api/tasks/*, /api/years
        ├── expenses.py      # /api/expenses/*, /api/taxes/*
        ├── equipment.py     # /api/equipment/*, /api/maintenance/*, /api/consumables/*
        ├── deals.py         # /api/deals/*, комментарии, взаимодействия
        ├── files.py         # /api/files/*
        ├── notes.py         # /api/notes/*, /api/admin/audit-log, /api/bot-faq
        ├── analytics.py     # /api/analytics/*, /api/budget/*, /api/export/*
        └── admin.py         # /api/service/*, /api/version
```

> `.env` хранится вне репозитория: `/etc/crm/.env`

---

## Быстрый старт (локально)

```bash
git clone <URL> && cd GCRM-2
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # заполнить переменные
uvicorn main:app --reload --port 8000
```

Swagger UI: `http://127.0.0.1:8000/docs`

### Переменные окружения (`.env`)

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
AUTH0_DOMAIN=your-domain.auth0.com
AUTH0_CLIENT_ID=...
AUTH0_CLIENT_SECRET=...
AUTH0_AUDIENCE=...
APP_BASE_URL=http://localhost:8000
SESSION_SECRET=случайная-строка
INTERNAL_API_KEY=случайная-строка       # для бота и внутренних вызовов
TELEGRAM_OWNER_ID=29635426              # личный Telegram ID владельца (алерты и уведомления)
OPENAI_BASE_URL=https://...             # OpenAI-совместимый эндпоинт
OPENAI_ACCESS_ID=...                    # ID агента / ключ
OPENAI_MODEL=deepseek-chat
API_BASE_URL=http://127.0.0.1:8000/api  # используется assistant_bot
TELEGRAM_BOT_TOKEN=...                  # основной бот (bot.py)
TELEGRAM_CHAT_ID=...                    # chat_id группы для уведомлений о сделках
TELEGRAM_ASSISTANT_BOT_TOKEN=...        # личный AI-ассистент (assistant_bot.py)
```

---

## Деплой на сервере

### Параметры

| | |
|---|---|
| Сервер | VPS Timeweb Cloud, Ubuntu 24.04 |
| IP | 77.232.134.112 |
| Путь | `/var/www/crm/GCRM-2` |
| Venv | `/var/www/crm/venv` |
| Порт | 127.0.0.1:8000 (за nginx/proxy) |
| Домен CRM | crmpokos.ru |
| Домен сайта | покос-ропша.рф → `/var/www/site` |
| `.env` | `/etc/crm/.env` (вне репозитория) |

### Автодеплой (GitHub Actions)

При любом `git push` в `main` GitHub Actions автоматически запускает `deploy.sh` на сервере через SSH.

Секреты в GitHub → Settings → Secrets → Actions:

| Секрет | Значение |
|---|---|
| `VPS_HOST` | IP сервера |
| `VPS_USER` | `root` |
| `VPS_SSH_KEY` | приватный SSH-ключ (`~/.ssh/github_deploy`) |
| `VPS_PORT` | `22` |

### Деплой вручную

```bash
cd /var/www/crm/GCRM-2
bash deploy.sh
```

### systemd сервисы и таймеры

| Юнит | Тип | Описание |
|---|---|---|
| `crm.service` | service | FastAPI бэкенд (main.py) |
| `greencrm-bot.service` | service | Основной Telegram-бот (bot.py) |
| `greencrm-assistant-bot.service` | service | AI-ассистент (assistant_bot.py) |
| `crm-repeats.service` / `.timer` | timer | Повторные сделки — каждый час |
| `crm-archive.service` / `.timer` | timer | Архивные сделки → провал (30 дней) — каждый час |

```bash
# Статус сервисов
systemctl status crm greencrm-bot greencrm-assistant-bot

# Статус таймеров
systemctl status crm-repeats.timer crm-archive.timer
systemctl list-timers crm-*

# Логи таймеров
journalctl -u crm-repeats.service -n 20
journalctl -u crm-archive.service -n 20
```

### Установка systemd таймеров (один раз)

```bash
# Скопировать файлы
cp crm-repeats.service crm-repeats.timer /etc/systemd/system/
cp crm-archive.service crm-archive.timer /etc/systemd/system/

# Активировать
systemctl daemon-reload
systemctl enable --now crm-repeats.timer
systemctl enable --now crm-archive.timer
```

### systemd unit (`/etc/systemd/system/crm.service`)

```ini
[Unit]
Description=Grass CRM FastAPI
After=network.target

[Service]
User=root
WorkingDirectory=/var/www/crm/GCRM-2
EnvironmentFile=/etc/crm/.env
ExecStart=/var/www/crm/GCRM-2/start.sh
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

После изменения файла: `systemctl daemon-reload`

### nginx

Конфиги в `/etc/nginx/sites-enabled/`:

| Файл | Домен | Описание |
|---|---|---|
| (основной) | crmpokos.ru | HTTPS → FastAPI + статика CRM |
| `pokos-ropsha` | покос-ропша.рф | HTTPS → `/var/www/site` (лендинг) |

SSL-сертификаты Let's Encrypt, авто-обновление через certbot.

---

## Роли пользователей

Роль задаётся вручную в таблице `users` в Supabase (колонка `role`).

| Роль | Сделки | Задачи | Расходы | Аналитика | Бюджет |
|---|---|---|---|---|---|
| `Admin` | Все | Все | Полный доступ | ✅ | ✅ |
| `User` | Только свои | Только свои | Скрыты | ❌ | ❌ |

---

## Telegram-боты

### Основной бот (`bot.py`)

Бот для команды: создание сделок через диалог, ежедневные отчёты, выезды на день, уведомления о новых сделках в группу.

Запускается через systemd (`greencrm-bot.service`).

#### Команды

| Команда | Описание |
|---|---|
| `/newdeal` | Создать сделку (название → контакт → услуги) |
| `/newexpense` | Записать расход (категория → название → сумма) |
| `/today` | Выезды на сегодня |
| `/tomorrow` | Выезды на завтра |
| `/sendreport` | Отправить отчёт вручную |
| `/mydeals` | Мои сделки на сегодня |
| `/editlastdeal` | Редактировать последнюю сделку |
| `/voicenote` | Голосовая заметка к сделке |
| `/status` | Статус всех сервисов (только владелец) |

#### Авто-задания (Job Queue)

| Время (МСК) | Что делает |
|---|---|
| 18:00 | Ежедневный отчёт в группу |
| 20:00 | Напоминание владельцу о выездах на завтра (только если есть) |

#### Уведомления о сделках

При создании сделки через любой источник в группу отправляется уведомление:

```
Сделка №N — Название сделки

ДД.ММ.ГГГГ ЧЧ:ММ
Клиент: Имя
Телефон: +7...
Адрес: ...

Услуги:
  · Название × кол-во — сумма ₽

Итого: сумма ₽
```

#### Алерты об ошибках

500-ошибки и краши бэкенда отправляются владельцу в личку (`TELEGRAM_OWNER_ID`) мгновенно.

---

### Личный AI-агент (`assistant_bot.py`)

Личный бот владельца. Работает только с авторизованными пользователями. Запускается через systemd (`greencrm-assistant-bot.service`).

#### Архитектура

Все сообщения проходят через единый **tool router** — AI выбирает инструмент и возвращает структурированный JSON.

#### Возможности

| Что отправить | Что сделает бот |
|---|---|
| Любой текстовый запрос | Tool router → нужное действие или ответ |
| «Создай сделку и задачу позвонить завтра» | Цепочка: сделка + задача за один запрос |
| «Сколько стоит покос?» | Открывает прайс-лист с ценами |
| Фото чека | OCR → расход записан автоматически |
| Голосовое сообщение | Транскрипция через faster-whisper → обработка |
| Фото объекта | Прикрепляется к активной сделке |

#### Команды

| Команда | Описание |
|---|---|
| `/start` | Приветствие и справка |
| `/forget` | Очистить память ассистента |
| `/checkup` | Ручной запуск proactive-анализа CRM |

#### Proactive AI (автоматические проверки)

| Время | Что проверяет |
|---|---|
| 09:00 МСК | Просроченные задачи, выезды на сегодня и завтра |
| 19:00 МСК | Итоги дня: активные сделки, расходы/выручка за месяц |

Если проблем нет — бот молчит.

---

## AI внутри CRM (веб-интерфейс)

### AI-панель в карточке сделки

При открытии существующей сделки — вкладка **✨ AI** в нижней части карточки.

**Быстрые вопросы (чипы):**
- 💡 Рекомендации — что можно улучшить по сделке
- 📋 Итог сделки — краткое резюме
- ✅ Предложи задачи — что нужно сделать дальше
- 💬 Сообщение клиенту — готовый текст
- ✍️ Итог в комментарий — генерирует и сохраняет одним кликом

### AI-разбор аналитики

В разделе **Аналитика** → кнопка **✨ Проанализировать** внизу страницы.

---

## Мониторинг

### Healthcheck

```bash
curl https://crmpokos.ru/api/health
```

Возвращает: статус БД, использование диска, uptime.

### Версии компонентов

```bash
curl https://crmpokos.ru/api/version
```

Возвращает: версии backend, API, git commit, Python, FastAPI, SQLAlchemy, PostgreSQL, uptime.

### Логи

Структурированные логи с ротацией: `/var/log/crm/app.log` (10 MB × 5 файлов).

```bash
tail -f /var/log/crm/app.log
journalctl -u crm -f
```

---

## Безопасность

| Мера | Статус | Описание |
|------|--------|----------|
| RLS на всех таблицах БД | ✅ | PostgreSQL блокирует доступ на уровне БД |
| `.env` вне репозитория | ✅ | `/etc/crm/.env`, chmod 600 |
| Автодеплой через SSH-ключ | ✅ | GitHub Actions, без пароля |
| UFW Firewall | ✅ | Открыты только порты 22, 80, 443, 10050 |
| Rate limiting nginx | ✅ | Login: 5r/m, Public API: 30r/m |
| Security заголовки nginx | ✅ | HSTS, X-Frame-Options, nosniff и др. |
| Fail2ban | ✅ | Три jail: sshd, nginx-limit, nginx-badbots |
| Бэкапы в Object Storage | ✅ | Timeweb Cloud S3 |
| Telegram-алерты при 500 | ✅ | Мгновенно в личку владельца |
| Audit Log | ✅ | Журнал изменений в панели Сервис |

---

## Схема БД — миграции

Все миграции выполняются автоматически при старте приложения через `_ensure_*` функции в `app/migrations.py`. Вручную ничего применять не нужно.

Ключевые таблицы:

| Таблица | Описание |
|---|---|
| `deals` | Сделки (включая `duration_hours`, `repeat_interval_days`, `next_repeat_date`) |
| `contacts` | Контакты клиентов |
| `deal_services` / `deal_electric_services` | Услуги в сделках с ценой на момент |
| `deal_materials` | Материалы в сделках |
| `stages` | Этапы канбана (по проекту) |
| `services` / `electric_services` | Каталоги услуг |
| `expenses` | Расходы |
| `tasks` | Задачи |
| `audit_log` | Журнал изменений |
| `ai_memory` | Долгосрочная память AI-ассистента |
| `notes` | Заметки пользователей |

---

## API — ключевые эндпоинты

### Сделки

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/deals` | Список сделок (поддерживает `?q=` для поиска) |
| `POST` | `/api/deals` | Создать сделку |
| `PATCH` | `/api/deals/{id}` | Обновить сделку |
| `DELETE` | `/api/deals/{id}` | Удалить сделку |
| `POST` | `/api/deals/{id}/duplicate` | Дублировать сделку |
| `POST` | `/api/deals/{id}/archive` | Архивировать сделку |

### Аналитика

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/analytics` | Основная аналитика за год |
| `GET` | `/api/analytics/seasons` | Сезонное сравнение год к году |
| `GET` | `/api/analytics/clients` | Маржинальность по клиентам |
| `GET` | `/api/analytics/weekdays` | Загрузка по дням недели |

### Сервис

| Метод | Путь | Описание |
|---|---|---|
| `GET` | `/api/health` | Healthcheck (публичный) |
| `GET` | `/api/version` | Версии всех компонентов |
| `GET` | `/api/service/status` | Статус системы (CPU, RAM, диск) |
| `GET` | `/api/service/run-repeats` | Запустить проверку повторных сделок |
| `GET` | `/api/service/run-archive` | Запустить проверку архивных сделок |
| `GET` | `/api/admin/audit-log` | Журнал изменений (Admin) |
| `POST` | `/api/service/backup` | Создать бэкап БД (Admin) |
| `POST` | `/api/service/restart` | Перезапустить сервис (Admin) |

---

## Резервное копирование

### Автоматически

Через cron в 03:00. Хранятся последние 2 дампа локально + копия в Timeweb Object Storage.

```
/var/www/crm/GCRM-2/backups/backup-YYYY-MM-DD.sql.gz
```

### Вручную из CRM

Панель управления → «База данных» → **«💾 Создать бэкап сейчас»**.

### Вручную из консоли

```bash
/var/www/crm/GCRM-2/backup.sh
```

### Восстановление

```bash
gunzip < backups/backup-2026-03-06.sql.gz | psql -d "$DATABASE_URL"
```

> ⚠️ Восстановление **перезаписывает** текущую БД.
