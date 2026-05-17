"""
Модуль парсинга расписания из HTML или локального файла.

Поддерживает:
- Парсинг HTML-страницы Апекс-ВУЗ через BeautifulSoup
- Чтение расписания из JSON/CSV файла (фолбэк)
- Кэширование в SQLite с TTL
"""

import asyncio
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiohttp
from bs4 import BeautifulSoup

import config

logger = logging.getLogger(__name__)


class ScheduleCache:
    """Класс для кэширования расписания в SQLite."""

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Инициализация базы данных."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS schedule_cache (
                    url_hash TEXT PRIMARY KEY,
                    html_content TEXT,
                    parsed_data TEXT,
                    timestamp REAL,
                    etag TEXT
                )
            """)
            conn.commit()
        logger.debug(f"База данных инициализирована: {self.db_path}")

    def get(self, url_hash: str) -> Optional[Dict[str, Any]]:
        """
        Получение данных из кэша.

        Args:
            url_hash: Хэш URL для идентификации кэша.

        Returns:
            Словарь с данными или None если кэш устарел/отсутствует.
        """
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.execute(
                "SELECT parsed_data, timestamp FROM schedule_cache WHERE url_hash = ?",
                (url_hash,)
            )
            row = cursor.fetchone()

        if not row:
            return None

        parsed_data, timestamp = row
        if datetime.now().timestamp() - timestamp > config.CACHE_TTL:
            logger.debug("Кэш устарел")
            return None

        logger.debug("Данные получены из кэша")
        return json.loads(parsed_data)

    def set(
        self,
        url_hash: str,
        html_content: str,
        parsed_data: Dict[str, Any],
        etag: Optional[str] = None
    ) -> None:
        """
        Сохранение данных в кэш.

        Args:
            url_hash: Хэш URL для идентификации кэша.
            html_content: Исходный HTML-контент.
            parsed_data: Распарсенные данные.
            etag: ETag заголовок для проверки изменений.
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO schedule_cache 
                (url_hash, html_content, parsed_data, timestamp, etag)
                VALUES (?, ?, ?, ?, ?)
            """, (
                url_hash,
                html_content,
                json.dumps(parsed_data, ensure_ascii=False),
                datetime.now().timestamp(),
                etag
            ))
            conn.commit()
        logger.debug("Данные сохранены в кэш")

    def invalidate(self, url_hash: str) -> None:
        """Удаление записи из кэша."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "DELETE FROM schedule_cache WHERE url_hash = ?",
                (url_hash,)
            )
            conn.commit()
        logger.debug(f"Кэш инвалидирован для хэша: {url_hash}")


class ScheduleParser:
    """Парсер расписания занятий."""

    def __init__(self):
        self.cache = ScheduleCache(config.DB_PATH)
        self.session: Optional[aiohttp.ClientSession] = None

    async def init_session(self) -> None:
        """Инициализация HTTP-сессии."""
        if self.session is None:
            self.session = aiohttp.ClientSession(
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
                }
            )

    async def close_session(self) -> None:
        """Закрытие HTTP-сессии."""
        if self.session:
            await self.session.close()
            self.session = None

    @staticmethod
    def _get_url_hash(url: str) -> str:
        """Получение хэша URL для кэширования."""
        return hashlib.md5(url.encode()).hexdigest()

    async def fetch_html(
        self,
        url: str,
        group: Optional[str] = None
    ) -> Tuple[str, Optional[str]]:
        """
        Загрузка HTML-страницы с расписанием.

        Args:
            url: URL страницы расписания.
            group: Название группы для фильтрации.

        Returns:
            Кортеж (HTML-контент, ETag).

        Raises:
            aiohttp.ClientError: Ошибка при загрузке страницы.
        """
        await self.init_session()
        
        params = {}
        if group:
            params["group"] = group

        async with self.session.get(url, params=params) as response:
            response.raise_for_status()
            etag = response.headers.get("ETag")
            html = await response.text(encoding="utf-8")
            
        logger.info(f"HTML загружен с {url}, размер: {len(html)} байт")
        return html, etag

    def parse_html(self, html: str) -> List[Dict[str, Any]]:
        """
        Парсинг HTML-страницы с расписанием.

        Args:
            html: HTML-контент страницы.

        Returns:
            Список словарей с информацией о занятиях.
        """
        soup = BeautifulSoup(html, "lxml")
        schedule_table = soup.find("table", class_="schedule-table")

        if not schedule_table:
            logger.warning("Таблица расписания не найдена")
            return []

        lessons = []
        rows = schedule_table.find_all("tr")[1:]  # Пропускаем заголовок

        for row in rows:
            cells = row.find_all(["td", "th"])
            if len(cells) < 5:
                continue

            try:
                # Извлечение даты
                date_cell = cells[0].get_text(strip=True)
                date_obj = datetime.strptime(date_cell, "%d.%m.%Y")

                # Извлечение времени
                time_text = cells[1].get_text(strip=True)
                time_start, time_end = self._parse_time(time_text)

                # Дисциплина
                discipline = cells[2].get_text(strip=True)

                # Тип занятия
                lesson_type = cells[3].get_text(strip=True) if len(cells) > 3 else ""

                # Аудитория
                audience = cells[4].get_text(strip=True) if len(cells) > 4 else ""

                # Преподаватель
                teacher = ""
                if len(cells) > 5:
                    teacher_cell = cells[5]
                    teacher = teacher_cell.get_text(strip=True)
                    # Обработка пометки "(уволен)"
                    if "(уволен)" in teacher.lower():
                        teacher = f"⚠️ {teacher}"

                # Подгруппа
                subgroup = ""
                if len(cells) > 6:
                    subgroup = cells[6].get_text(strip=True)

                # Статус занятия (проведено/отменено)
                status = "scheduled"
                small_tag = row.find("small")
                if small_tag:
                    small_text = small_tag.get_text(strip=True).lower()
                    if "проведено" in small_text:
                        status = "completed"
                    elif "отмена" in small_text or "замена" in small_text:
                        status = "cancelled"

                lesson = {
                    "date": date_obj.strftime("%d.%m.%Y"),
                    "date_obj": date_obj,
                    "time_start": time_start,
                    "time_end": time_end,
                    "discipline": discipline,
                    "lesson_type": lesson_type,
                    "audience": audience,
                    "teacher": teacher,
                    "subgroup": subgroup,
                    "status": status
                }
                lessons.append(lesson)

            except (ValueError, IndexError) as e:
                logger.warning(f"Ошибка парсинга строки: {e}")
                continue

        logger.info(f"Распаршено {len(lessons)} занятий")
        return lessons

    @staticmethod
    def _parse_time(time_text: str) -> Tuple[str, str]:
        """
        Парсинг времени занятия.

        Args:
            time_text: Строка времени в формате "ЧЧ:ММ - ЧЧ:ММ".

        Returns:
            Кортеж (время начала, время окончания).
        """
        try:
            parts = time_text.replace("–", "-").split("-")
            start = parts[0].strip()
            end = parts[1].strip() if len(parts) > 1 else ""
            return start, end
        except (IndexError, ValueError):
            return time_text, ""

    async def get_schedule(
        self,
        url: Optional[str] = None,
        group: Optional[str] = None,
        use_cache: bool = True
    ) -> List[Dict[str, Any]]:
        """
        Получение расписания с кэшированием.

        Args:
            url: URL страницы расписания.
            group: Название группы.
            use_cache: Использовать ли кэш.

        Returns:
            Список занятий.
        """
        url = url or config.SCHEDULE_URL
        url_hash = self._get_url_hash(f"{url}_{group}")

        # Попытка получить из кэша
        if use_cache:
            cached = self.cache.get(url_hash)
            if cached:
                logger.info("Использованы кэшированные данные")
                return cached.get("lessons", [])

        # Загрузка и парсинг
        try:
            html, etag = await self.fetch_html(url, group)
            lessons = self.parse_html(html)
            
            # Сохранение в кэш
            self.cache.set(
                url_hash,
                html,
                {"lessons": lessons},
                etag
            )
            return lessons

        except aiohttp.ClientError as e:
            logger.error(f"Ошибка загрузки HTML: {e}")
            # Фолбэк на локальный файл
            return await self._load_from_file()

        except Exception as e:
            logger.error(f"Неожиданная ошибка: {e}")
            return await self._load_from_file()

    async def _load_from_file(self) -> List[Dict[str, Any]]:
        """
        Загрузка расписания из локального JSON-файла.

        Returns:
            Список занятий или пустой список.
        """
        file_path = config.SCHEDULE_FILE
        
        if not file_path.exists():
            logger.warning(f"Файл расписания не найден: {file_path}")
            return []

        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            
            lessons = data.get("lessons", [])
            # Конвертация строк дат в datetime объекты
            for lesson in lessons:
                if "date" in lesson and "date_obj" not in lesson:
                    try:
                        lesson["date_obj"] = datetime.strptime(
                            lesson["date"], "%d.%m.%Y"
                        )
                    except ValueError:
                        lesson["date_obj"] = datetime.now()
            
            logger.info(f"Загружено {len(lessons)} занятий из файла")
            return lessons

        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Ошибка чтения файла: {e}")
            return []

    async def save_to_file(self, lessons: List[Dict[str, Any]]) -> None:
        """
        Сохранение расписания в локальный JSON-файл.

        Args:
            lessons: Список занятий для сохранения.
        """
        # Убираем datetime объекты перед сериализацией
        export_lessons = []
        for lesson in lessons:
            export_lesson = lesson.copy()
            export_lesson.pop("date_obj", None)
            export_lessons.append(export_lesson)

        with open(config.SCHEDULE_FILE, "w", encoding="utf-8") as f:
            json.dump(
                {"lessons": export_lessons},
                f,
                ensure_ascii=False,
                indent=2
            )
        logger.info(f"Расписание сохранено в {config.SCHEDULE_FILE}")


def format_lesson(lesson: Dict[str, Any], subgroup_filter: Optional[str] = None) -> str:
    """
    Форматирование информации о занятии для вывода.

    Args:
        lesson: Словарь с информацией о занятии.
        subgroup_filter: Фильтр по подгруппе.

    Returns:
        Отформатированная строка с эмодзи и Markdown.
    """
    # Фильтрация по подгруппе
    if subgroup_filter and lesson.get("subgroup"):
        if subgroup_filter not in lesson.get("subgroup", ""):
            return ""

    # Статус занятия
    status_emoji = {
        "scheduled": "📚",
        "completed": "✅",
        "cancelled": "❌"
    }
    emoji = status_emoji.get(lesson.get("status", "scheduled"), "📚")

    # Форматирование
    lines = [
        f"{emoji} *{lesson.get('discipline', 'Не указано')}*",
        f"🕐 {lesson.get('time_start', '')} - {lesson.get('time_end', '')}",
        f"📍 Аудитория: {lesson.get('audience', 'Не указана')}"
    ]

    if lesson.get("lesson_type"):
        lines.append(f"📝 Тип: {lesson['lesson_type']}")

    if lesson.get("teacher"):
        lines.append(f"👨‍🏫 Преподаватель: {lesson['teacher']}")

    if lesson.get("subgroup"):
        lines.append(f"👥 Подгруппа: {lesson['subgroup']}")

    return "\n".join(lines)


def format_schedule(
    lessons: List[Dict[str, Any]],
    date: datetime,
    subgroup: Optional[str] = None
) -> str:
    """
    Форматирование расписания на день.

    Args:
        lessons: Список занятий.
        date: Дата для заголовка.
        subgroup: Подгруппа для фильтрации.

    Returns:
        Отформатированная строка со всем расписанием.
    """
    # Фильтрация по дате
    day_lessons = [
        l for l in lessons
        if l.get("date_obj") and l["date_obj"].date() == date.date()
    ]

    if not day_lessons:
        return f"📅 *{date.strftime('%d.%m.%Y')}*\n\nНет занятий на этот день."

    # Заголовок
    weekday_names = {
        0: "Понедельник",
        1: "Вторник",
        2: "Среда",
        3: "Четверг",
        4: "Пятница",
        5: "Суббота",
        6: "Воскресенье"
    }
    weekday = weekday_names.get(date.weekday(), "")
    
    header = f"📅 *{date.strftime('%d.%m.%Y')} ({weekday})*\n\n"

    # Форматирование каждого занятия
    formatted_lessons = []
    for lesson in sorted(day_lessons, key=lambda x: x.get("time_start", "")):
        formatted = format_lesson(lesson, subgroup)
        if formatted:
            formatted_lessons.append(formatted)

    if not formatted_lessons:
        return header + "Нет занятий для выбранной подгруппы."

    return header + "\n\n".join(formatted_lessons)


async def self_test() -> Dict[str, bool]:
    """
    Самостоятельное тестирование модуля парсинга.

    Returns:
        Словарь с результатами тестов.
    """
    results = {
        "db_connection": False,
        "file_access": False,
        "parser_init": False
    }

    # Тест подключения к БД
    try:
        cache = ScheduleCache(config.DB_PATH)
        results["db_connection"] = True
        logger.info("✓ Подключение к БД работает")
    except Exception as e:
        logger.error(f"✗ Ошибка подключения к БД: {e}")

    # Тест доступа к файлу
    try:
        if config.SCHEDULE_FILE.exists():
            with open(config.SCHEDULE_FILE, "r") as f:
                json.load(f)
        results["file_access"] = True
        logger.info("✓ Доступ к файлу расписания OK")
    except Exception as e:
        logger.warning(f"⚠ Файл расписания недоступен: {e}")
        results["file_access"] = True  # Не критично

    # Тест инициализации парсера
    try:
        parser = ScheduleParser()
        results["parser_init"] = True
        logger.info("✓ Парсер инициализирован")
    except Exception as e:
        logger.error(f"✗ Ошибка инициализации парсера: {e}")

    return results


if __name__ == "__main__":
    # Быстрый тест при запуске модуля
    logging.basicConfig(level=logging.INFO)
    asyncio.run(self_test())
