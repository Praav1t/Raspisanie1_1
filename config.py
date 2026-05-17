"""
Конфигурация Telegram-бота для просмотра расписания.

Вынесите чувствительные данные в переменные окружения или заполните вручную.
"""

import os
from pathlib import Path

# Токен бота (получить у @BotFather)
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_BOT_TOKEN_HERE")

# URL страницы расписания Апекс-ВУЗ
SCHEDULE_URL = os.getenv(
    "SCHEDULE_URL",
    "https://apex-vuz.ru/schedule"  # Замените на актуальный URL
)

# Путь к локальному файлу с расписанием (фолбэк)
SCHEDULE_FILE = Path(os.getenv("SCHEDULE_FILE", "schedule_data.json"))

# Название группы по умолчанию
DEFAULT_GROUP = os.getenv("DEFAULT_GROUP", "Б-ИСиТ-21")

# Поддерживаемые подгруппы
SUBGROUPS = ["1", "2"]

# TTL кэша в секундах (1 час)
CACHE_TTL = 3600

# Путь к базе данных SQLite
DB_PATH = Path(os.getenv("DB_PATH", "schedule_cache.db"))

# Лог-файл
LOG_FILE = Path(os.getenv("LOG_FILE", "bot.log"))

# Уровень логирования
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
