"""
Telegram-бот для просмотра расписания занятий.

Использует aiogram 3.x для асинхронной работы.
Команды: /start, /today, /tomorrow, /week, /help
"""

import asyncio
import logging
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import Message
from aiogram.enums import ParseMode

import config
from parser import ScheduleParser, format_schedule, self_test as parser_self_test

# Настройка логирования
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Создание роутера для хендлеров
router = Router()

# Глобальный парсер
parser: Optional[ScheduleParser] = None


async def get_or_create_parser() -> ScheduleParser:
    """Получение или создание экземпляра парсера."""
    global parser
    if parser is None:
        parser = ScheduleParser()
    return parser


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    """
    Обработчик команды /start.

    Приветствует пользователя и показывает краткую справку.
    """
    await message.answer(
        f"👋 *Добро пожаловать в бот расписания!*\\n\\n"
        f"Я помогу вам узнать расписание занятий группы *{config.DEFAULT_GROUP}*\\.\\n\\n"
        f"*Доступные команды:*\\n"
        f"/today \\- Расписание на сегодня\\n"
        f"/tomorrow \\- Расписание на завтра\\n"
        f"/week \\[номер\\] \\- Расписание на неделю\\n"
        f"/subgroup \\[1\\|2\\] \\- Выбор подгруппы\\n"
        f"/help \\- Подробная справка\\n\\n"
        f"Нажмите /help для получения подробной информации\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info(f"Команда /start от пользователя {message.from_user.id}")


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    """
    Обработчик команды /today.

    Показывает расписание на текущий день.
    """
    await message.answer("⏳ Загружаю расписание на сегодня...")
    
    try:
        p = await get_or_create_parser()
        lessons = await p.get_schedule()
        
        today = datetime.now()
        subgroup = _get_user_subgroup(message.from_user.id)
        
        schedule_text = format_schedule(lessons, today, subgroup)
        
        await message.answer(
            schedule_text,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Команда /today от пользователя {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении /today: {e}")
        await message.answer(
            "❌ Произошла ошибка при загрузке расписания\\.\\n"
            "Попробуйте позже или используйте команду /help\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


@router.message(Command("tomorrow"))
async def cmd_tomorrow(message: Message) -> None:
    """
    Обработчик команды /tomorrow.

    Показывает расписание на завтрашний день.
    """
    await message.answer("⏳ Загружаю расписание на завтра...")
    
    try:
        p = await get_or_create_parser()
        lessons = await p.get_schedule()
        
        tomorrow = datetime.now() + timedelta(days=1)
        subgroup = _get_user_subgroup(message.from_user.id)
        
        schedule_text = format_schedule(lessons, tomorrow, subgroup)
        
        await message.answer(
            schedule_text,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Команда /tomorrow от пользователя {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении /tomorrow: {e}")
        await message.answer(
            "❌ Произошла ошибка при загрузке расписания\\.\\n"
            "Попробуйте позже или используйте команду /help\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


@router.message(Command("week"))
async def cmd_week(message: Message) -> None:
    """
    Обработчик команды /week.

    Показывает расписание на указанную неделю.
    Поддерживает аргумент: номер недели (1-52).
    """
    args = message.text.split()
    
    # Парсинг номера недели
    week_number = None
    if len(args) > 1:
        try:
            week_number = int(args[1])
            if not 1 <= week_number <= 52:
                raise ValueError("Недопустимый номер недели")
        except ValueError:
            await message.answer(
                "❌ Неверный формат номера недели\\.\\n"
                "Используйте: `/week <номер>` где номер от 1 до 52\\.",
                parse_mode=ParseMode.MARKDOWN_V2
            )
            return
    
    await message.answer("⏳ Загружаю расписание на неделю...")
    
    try:
        p = await get_or_create_parser()
        lessons = await p.get_schedule()
        
        # Определение даты начала недели
        today = datetime.now()
        if week_number:
            # Если указана конкретная неделя
            current_week = today.isocalendar()[1]
            week_diff = week_number - current_week
            start_date = today + timedelta(weeks=week_diff)
            # Корректировка до понедельника
            start_date = start_date - timedelta(days=start_date.weekday())
        else:
            # Текущая неделя
            start_date = today - timedelta(days=today.weekday())
        
        subgroup = _get_user_subgroup(message.from_user.id)
        
        # Формирование расписания на 7 дней
        schedule_parts = []
        for i in range(7):
            day_date = start_date + timedelta(days=i)
            day_schedule = format_schedule(lessons, day_date, subgroup)
            if day_schedule and "Нет занятий" not in day_schedule:
                schedule_parts.append(day_schedule)
        
        if not schedule_parts:
            result_text = f"📅 Неделя {week_number or 'текущая'}\\n\\nНет занятий на этой неделе\\."
        else:
            result_text = f"📅 *Неделя {week_number or 'текущая'}*\\n\\n" + "\\n\\n".join(schedule_parts)
        
        await message.answer(
            result_text,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Команда /week от пользователя {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении /week: {e}")
        await message.answer(
            "❌ Произошла ошибка при загрузке расписания\\.\\n"
            "Попробуйте позже или используйте команду /help\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


@router.message(Command("subgroup"))
async def cmd_subgroup(message: Message) -> None:
    """
    Обработчик команды /subgroup.

    Устанавливает подгруппу пользователя (1 или 2).
    """
    args = message.text.split()
    
    if len(args) < 2:
        await message.answer(
            "👥 *Выбор подгруппы*\\n\\n"
            "Используйте: `/subgroup 1` или `/subgroup 2`\\n\\n"
            "Это позволит фильтровать расписание по вашей подгруппе\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    subgroup = args[1]
    if subgroup not in config.SUBGROUPS:
        await message.answer(
            f"❌ Недопустимое значение подгруппы\\.\n"
            f"Допустимые значения: {', '.join(config.SUBGROUPS)}\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )
        return
    
    # Сохранение подгруппы (в реальном проекте использовать БД)
    _set_user_subgroup(message.from_user.id, subgroup)
    
    await message.answer(
        f"✅ Подгруппа *{subgroup}* установлена\\.\n"
        f"Теперь расписание будет фильтроваться по вашей подгруппе\\.",
        parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info(f"Пользователь {message.from_user.id} установил подгруппу {subgroup}")


@router.message(Command("help"))
async def cmd_help(message: Message) -> None:
    """
    Обработчик команды /help.

    Показывает подробную справку по боту.
    """
    help_text = (
        "📖 *Справка по боту расписания*\\n\\n"
        f"*Группа:* {config.DEFAULT_GROUP}\\n\\n"
        "*Команды:*\\n"
        "/start \\- Приветствие\\n"
        "/today \\- Расписание на сегодня\\n"
        "/tomorrow \\- Расписание на завтра\\n"
        "/week \\[номер\\] \\- Расписание на неделю \\(1\\-52\\)\\n"
        "/subgroup \\[1\\|2\\] \\- Выбор подгруппы\\n"
        "/help \\- Эта справка\\n\\n"
        "*Особенности:*\\n"
        "• Кэширование данных \\(1 час\\)\\n"
        "• Поддержка подгрупп\\n"
        "• Автоматическое определение статуса занятий\\n"
        "• Работа при недоступности сайта\\n\\n"
        "*Формат вывода:*\\n"
        "📚 Дисциплина\\n"
        "🕐 Время\\n"
        "📍 Аудитория\\n"
        "👨‍🏫 Преподаватель\\n"
        "👥 Подгруппа\\n\\n"
        "При возникновении проблем обратитесь к администратору\\."
    )
    
    await message.answer(
        help_text,
        parse_mode=ParseMode.MARKDOWN_V2
    )
    logger.info(f"Команда /help от пользователя {message.from_user.id}")


@router.message(Command("next"))
async def cmd_next(message: Message) -> None:
    """
    Обработчик команды /next.

    Показывает расписание на следующий учебный день.
    """
    await message.answer("⏳ Определяю следующий учебный день...")
    
    try:
        p = await get_or_create_parser()
        lessons = await p.get_schedule()
        
        # Поиск следующего учебного дня
        today = datetime.now()
        next_day = today
        
        for _ in range(7):  # Ищем максимум неделю вперед
            next_day = next_day + timedelta(days=1)
            # Пропускаем выходные (5=суббота, 6=воскресенье)
            if next_day.weekday() < 5:
                # Проверяем, есть ли занятия в этот день
                day_lessons = [
                    l for l in lessons
                    if l.get("date_obj") and l["date_obj"].date() == next_day.date()
                ]
                if day_lessons:
                    break
        
        subgroup = _get_user_subgroup(message.from_user.id)
        schedule_text = format_schedule(lessons, next_day, subgroup)
        
        await message.answer(
            f"📅 *Следующий учебный день:* {next_day.strftime('%d.%m.%Y')}\\n\\n" + schedule_text,
            parse_mode=ParseMode.MARKDOWN
        )
        logger.info(f"Команда /next от пользователя {message.from_user.id}")
        
    except Exception as e:
        logger.error(f"Ошибка при выполнении /next: {e}")
        await message.answer(
            "❌ Произошла ошибка при определении следующего учебного дня\\.",
            parse_mode=ParseMode.MARKDOWN_V2
        )


# Хранилище подгрупп пользователей (в памяти)
# В реальном проекте использовать базу данных
_user_subgroups: Dict[int, str] = {}


def _get_user_subgroup(user_id: int) -> Optional[str]:
    """Получение подгруппы пользователя."""
    return _user_subgroups.get(user_id)


def _set_user_subgroup(user_id: int, subgroup: str) -> None:
    """Установка подгруппы пользователя."""
    _user_subgroups[user_id] = subgroup


async def self_test(bot: Bot) -> Dict[str, bool]:
    """
    Комплексное тестирование бота при запуске.

    Args:
        bot: Экземпляр бота для проверки токена.

    Returns:
        Словарь с результатами тестов.
    """
    results = {
        "bot_token": False,
        "internet_connection": False,
        "site_access": False,
        "database": False,
        "schedule_file": False
    }

    logger.info("=" * 50)
    logger.info("ЗАПУСК ТЕСТИРОВАНИЯ БОТА")
    logger.info("=" * 50)

    # Тест токена бота
    try:
        bot_info = await bot.get_me()
        results["bot_token"] = True
        logger.info(f"✓ Токен бота валиден. Бот: @{bot_info.username}")
    except Exception as e:
        logger.error(f"✗ Ошибка токена бота: {e}")

    # Тест подключения к интернету
    try:
        async with __import__("aiohttp").ClientSession() as session:
            async with session.get("https://google.com", timeout=5) as response:
                results["internet_connection"] = True
                logger.info("✓ Подключение к интернету работает")
    except Exception as e:
        logger.warning(f"⚠ Нет подключения к интернету: {e}")

    # Тест доступности сайта
    try:
        async with __import__("aiohttp").ClientSession() as session:
            async with session.get(config.SCHEDULE_URL, timeout=10) as response:
                if response.status == 200:
                    results["site_access"] = True
                    logger.info(f"✓ Сайт расписания доступен ({config.SCHEDULE_URL})")
                else:
                    logger.warning(f"⚠ Сайт вернул статус {response.status}")
    except Exception as e:
        logger.warning(f"⚠ Сайт недоступен: {e}")
        results["site_access"] = False  # Не критично, есть фолбэк

    # Тест базы данных
    try:
        parser_test_results = await parser_self_test()
        results["database"] = parser_test_results.get("db_connection", False)
    except Exception as e:
        logger.error(f"✗ Ошибка теста БД: {e}")

    # Тест файла расписания
    if config.SCHEDULE_FILE.exists():
        results["schedule_file"] = True
        logger.info(f"✓ Файл расписания найден: {config.SCHEDULE_FILE}")
    else:
        logger.info("ℹ Файл расписания не найден (будет создан при первом парсинге)")
        results["schedule_file"] = True  # Не критично

    logger.info("=" * 50)
    logger.info("РЕЗУЛЬТАТЫ ТЕСТИРОВАНИЯ:")
    for test_name, passed in results.items():
        status = "✓" if passed else "✗"
        logger.info(f"{status} {test_name}: {'PASS' if passed else 'FAIL'}")
    logger.info("=" * 50)

    return results


async def main() -> None:
    """
    Точка входа приложения.

    Последовательность:
    1. Инициализация бота и диспетчера
    2. Запуск тестирования
    3. Регистрация хендлеров
    4. Запуск polling
    """
    # Проверка токена
    if config.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        logger.critical("❌ BOT_TOKEN не настроен! Отредактируйте config.py")
        sys.exit(1)

    # Создание бота и диспетчера
    bot = Bot(token=config.BOT_TOKEN)
    dp = Dispatcher()

    # Регистрация роутера
    dp.include_router(router)

    # Запуск тестирования
    await self_test(bot)

    logger.info("🚀 ЗАПУСК БОТА...")
    
    try:
        # Запуск polling
        await dp.start_polling(bot)
    except KeyboardInterrupt:
        logger.info("Получен сигнал остановки")
    except Exception as e:
        logger.critical(f"Критическая ошибка: {e}")
        raise
    finally:
        # Закрытие сессии парсера при остановке
        if parser:
            await parser.close_session()
        await bot.session.close()
        logger.info("Бот остановлен")


if __name__ == "__main__":
    # Запуск через asyncio.run для Python 3.7+
    asyncio.run(main())
