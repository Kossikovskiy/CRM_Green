import sys
import os

# Указываем путь к интерпретатору Python в виртуальном окружении на хостинге
# ПУТЬ НУЖНО БУДЕТ ЗАМЕНИТЬ НА ВАШ РЕАЛЬНЫЙ ПОСЛЕ ЗАГРУЗКИ НА ХОСТИНГ!
INTERP = os.path.expanduser("/var/www/ваш_пользователь/data/venv/bin/python")
if sys.executable != INTERP:
    os.execl(INTERP, INTERP, *sys.argv)

# Добавляем путь к корню проекта в sys.path
# ПУТЬ НУЖНО БУДЕТ ЗАМЕНИТЬ НА ВАШ РЕАЛЬНЫЙ!
sys.path.insert(0, '/var/www/ваш_пользователь/data/www/ваш-домен.ru')

# Импортируем WSGI-приложение из файла api/main.py (где мы создали application)
from api.main import application

# Необязательно, но можно добавить для логирования
import logging
logging.basicConfig(stream=sys.stderr, level=logging.INFO)