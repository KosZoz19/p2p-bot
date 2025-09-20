import asyncio
import json
import os
import logging
from pathlib import Path
from time import time
from typing import Dict, Any
from aiogram.types import Update
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, ChatJoinRequest, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramEntityTooLarge
from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F

logging.basicConfig(level=logging.INFO)

import asyncio
import json
import os
import logging
import random
from pathlib import Path
from time import time
from typing import Dict, Any
from aiogram.types import Update
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, ChatJoinRequest, InputMediaPhoto, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError
from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F
from aiogram.exceptions import TelegramBadRequest

logging.basicConfig(level=logging.INFO)

# ========= ENV / INIT =========
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")

RUN_MODE = os.getenv("RUN_MODE", "polling")  # "webhook" on Render, "polling" locally
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "supersecret")
# External URL detection - works with multiple platforms
EXTERNAL_URL = (
    os.getenv("RENDER_EXTERNAL_URL") or  # Render.com
    os.getenv("RAILWAY_STATIC_URL") or  # Railway
    (os.getenv("REPLIT_DEV_DOMAIN") and f"https://{os.getenv('REPLIT_DEV_DOMAIN')}")
)
SITE_URL = os.getenv("SITE_URL", "https://koszoz19.github.io/p2p/")
LESSON_URL = os.getenv("LESSON_URL", SITE_URL)
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "0") or 0)  # запасной ID канала (-100...)
PORT = int(os.getenv("PORT", "10000"))

# отдельные ссылки на уроки
LESSON1_URL = os.getenv("LESSON1_URL", LESSON_URL)
LESSON2_URL = os.getenv("LESSON2_URL", LESSON_URL)
LESSON3_URL = os.getenv("LESSON3_URL", LESSON_URL)

# --- баннеры (из .env) ---
BANNER_WELCOME = os.getenv("BANNER_WELCOME", "")
BANNER_AFTER1 = os.getenv("BANNER_AFTER1", "")
BANNER_AFTER2 = os.getenv("BANNER_AFTER2", "")
BANNER_AFTER3 = os.getenv("BANNER_AFTER3", "")
BANNER_AFTER4 = os.getenv("BANNER_AFTER4", "")
BANNER_AFTER5 = os.getenv("BANNER_AFTER5", "")
BANNER_BLOCK6 = os.getenv("BANNER_BLOCK6", "")
BANNER_BLOCK7 = os.getenv("BANNER_BLOCK7", "")

WELCOME_VIDEO_FILE = os.getenv("WELCOME_VIDEO_FILE", "")  # e.g., "videos/welcome.mp4"

L3_FOLLOWUP_VIDEO = os.getenv("L3_FOLLOWUP_VIDEO", "")
L3_FOLLOWUP_CAPTION = os.getenv("L3_FOLLOWUP_CAPTION", "")
L3_FOLLOWUP_DELAY = int(os.getenv("L3_FOLLOWUP_DELAY", "10"))
# Теперь используем путь к файлу или file_id из .env
raw_l3 = os.getenv("L3_FOLLOWUP_FILE", "") or ""
L3_FOLLOWUP_FILE = raw_l3.strip().replace("\u200b", "").replace("\ufeff", "").replace("\u2060", "")
if L3_FOLLOWUP_FILE == "":
    L3_FOLLOWUP_FILE = ""

DIARY_TG_CHAT_ID = int(os.getenv("DIARY_TG_CHAT_ID", "0") or 0)
DIARY_TG_JOIN_URL = os.getenv("DIARY_TG_JOIN_URL", "")
DIARY_URL = os.getenv("DIARY_URL", "https://instagram.com/your_diary_here")
FORM_URL = os.getenv("FORM_URL", "https://forms.gle/your_form_here")

# задержки напоминаний
REM1_DELAY = int(os.getenv("REM1_DELAY", "120"))
REM2_DELAY = int(os.getenv("REM2_DELAY", "300"))
REM3_DELAY = int(os.getenv("REM3_DELAY", "600"))

# быстрые паузы для следующего тизера (после клика по текущему уроку)
NEXT_AFTER_1 = int(os.getenv("NEXT_AFTER_1", "8"))
NEXT_AFTER_2 = int(os.getenv("NEXT_AFTER_2", "8"))

# напоминалки до нажатия «ПОЛУЧИТЬ ДОСТУП»
ACCESS_REM_DELAYS = [
    int(x) for x in os.getenv("ACCESS_REM_DELAYS", "120,300,900").split(",")
    if x.strip().isdigit()
]

MARK_REMIND_DELAY_1 = int(os.getenv("MARK_REMIND_DELAY_1", "300"))
MARK_REMIND_DELAY_2 = int(os.getenv("MARK_REMIND_DELAY_2", "300"))

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
router = Router()
DEEP_LINK = ""  # заполним в main()
SENDING_POSTS: set[int] = set()  # chat_ids that are already sending course posts

# ========= ХРАНИЛКА ПРОГРЕССА (файл) =========
stats_file = DATA_DIR / "stats.json"
if not stats_file.exists():
    stats_file.write_text(json.dumps({"users": {}}, ensure_ascii=False, indent=2))

def _read() -> Dict[str, Any]:
    try:
        return json.loads(stats_file.read_text() or "{}")
    except Exception:
        return {"users": {}}

def _write(d: Dict[str, Any]):
    stats_file.write_text(json.dumps(d, ensure_ascii=False, indent=2))

def get_stage(uid: int) -> int:
    d = _read()
    return int(d.get("users", {}).get(str(uid), {}).get("stage", 0))

def set_stage(uid: int, stage: int):
    d = _read()
    u = d.setdefault("users", {}).setdefault(str(uid), {})
    u["stage"] = stage
    u["ts"] = int(time())
    _write(d)

def set_pm_ok(uid: int, ok: bool):
    d = _read()
    u = d.setdefault("users", {}).setdefault(str(uid), {})
    u["pm_ok"] = bool(ok)
    _write(d)

def can_pm(uid: int) -> bool:
    d = _read()
    return bool(d.get("users", {}).get(str(uid), {}).get("pm_ok", False))

def is_watched(uid: int, n: int) -> bool:
    d = _read()
    return bool(d.get("users", {}).get(str(uid), {}).get("watched", {}).get(str(n), False))

def set_watched(uid: int, n: int, watched: bool):
    d = _read()
    u = d.setdefault("users", {}).setdefault(str(uid), {})
    w = u.setdefault("watched", {})
    w[str(n)] = bool(watched)
    _write(d)

def set_diary_request(uid: int, requested: bool):
    """Фіксує, що юзер відправив заявку на підписку в дневник"""
    d = _read()
    u = d.setdefault("users", {}).setdefault(str(uid), {})
    u["diary_request"] = bool(requested)
    u["diary_ts"] = int(time())
    _write(d)
    logging.info("set_diary_request(uid=%s)=%s", uid, requested)

def has_diary_request(uid: int) -> bool:
    """Чи відправляв юзер заявку на підписку в дневник"""
    d = _read()
    val = bool(d.get("users", {}).get(str(uid), {}).get("diary_request", False))
    logging.info("has_diary_request(uid=%s) -> %s", uid, val)
    return val


def is_loop_stopped(uid: int) -> bool:
    d = _read()
    return bool(d.get("users", {}).get(str(uid), {}).get("loop_stopped", False))


def set_loop_stopped(uid: int, stopped: bool):
    d = _read()
    u = d.setdefault("users", {}).setdefault(str(uid), {})
    u["loop_stopped"] = bool(stopped)
    _write(d)


# ========= HELPER FUNCTIONS =========

async def send_block(chat_id: int, banner_url: str, text: str,
                     reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    try:
        if banner_url:
            await bot.send_photo(chat_id, banner_url, caption=text, reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except TelegramForbiddenError:
        logging.warning("TelegramForbiddenError in send_block for chat %s. User may have blocked the bot.", chat_id)
    except Exception:
        logging.exception("Unexpected error in send_block for chat %s", chat_id)

async def send_url_only(chat_id: int, url: str, reply_markup=None):
    """Отправить только ссылку (без текста)"""
    try:
        await bot.send_message(chat_id, url, reply_markup=reply_markup, disable_web_page_preview=False)
    except Exception:
        await bot.send_message(chat_id, url, reply_markup=reply_markup)

async def is_subscribed_telegram(user_id: int) -> bool:
    """True, если дневник = Telegram-канал и юзер там участник"""
    if not DIARY_TG_CHAT_ID:
        return False
    
    try:
        member = await bot.get_chat_member(DIARY_TG_CHAT_ID, user_id)
        return member.status in {
            ChatMemberStatus.MEMBER,
            ChatMemberStatus.ADMINISTRATOR,
            ChatMemberStatus.CREATOR,
        }
    except Exception:
        return False

def _looks_like_videonote(fid: str | None) -> bool:
    if not fid:
        return False
    # несколько известных префиксов, плюс проверка длины — простая эвристика
    return fid.startswith(("DQAC", "AQAD", "BAAD", "CAAD")) or len(fid) > 40

async def _send_l3_video_later(chat_id: int, delay: int | None = None):
    if not L3_FOLLOWUP_FILE:
        return
    await asyncio.sleep(delay if delay is not None else L3_FOLLOWUP_DELAY)
    await _send_file_with_fallback(chat_id, L3_FOLLOWUP_FILE, L3_FOLLOWUP_CAPTION or None)

async def auto_send_next_lesson(user_id: int, current_lesson: int):
    """Автоматически отправляет следующий урок через 30 минут"""
    await asyncio.sleep(30 * 0.1)  # 30 минут
    
    try:
        if current_lesson == 1:
            # После урока 1 -> отправляем блок и доступ к уроку 2
            await send_block(user_id, BANNER_AFTER3, AFTER_L1)
            await bot.send_message(user_id, "Открывай второй урок 👇", reply_markup=kb_open(2))
        elif current_lesson == 2:
            # После урока 2 -> отправляем блок перед уроком 3
            await send_block(user_id, BANNER_AFTER5, AFTER_L2)
            await bot.send_message(user_id, "Открывай третий урок 👇", reply_markup=kb_open(3))

    except Exception as e:
        logging.warning("auto_send_next_lesson failed: %s", e)

# ========= KEYBOARD FUNCTIONS =========
def kb_access() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔑 ПОЛУЧИТЬ ДОСТУП", callback_data="open:1"))
    return kb.as_markup()

def kb_open(n: int) -> InlineKeyboardMarkup:
    labels = {1: "ОТКРЫТЬ УРОК 1", 2: "ОТКРЫТЬ УРОК 2", 3: "ОТКРЫТЬ УРОК 3"}
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text=labels[n], callback_data=f"open:{n}"))
    return kb.as_markup()

# Функция kb_done убрана - теперь автоматическая отправка через 30 минут

def kb_subscribe_then_l3() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    if DIARY_TG_JOIN_URL:
        kb.row(InlineKeyboardButton(text="📓 Подписаться на дневник", url=DIARY_TG_JOIN_URL))
    else:
        kb.row(InlineKeyboardButton(text="📓 Подписаться на дневник", url=DIARY_URL))
    kb.row(InlineKeyboardButton(text="✅ Отправил запрос — ПРОВЕРИТЬ", callback_data="check_diary"))
    return kb.as_markup()

def kb_buy_course() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔥 Взять мини-курс (999 грн)", callback_data="buy_course"))
    return kb.as_markup()


def kb_apply_form() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="📝 Оставить заявку", url=FORM_URL))
    return kb.as_markup()

def kb_deeplink() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🎁 ПОЛУЧИТЬ УРОКИ", url=DEEP_LINK))
    return kb.as_markup()

# ========= TEXTS =========
def teaser_text(n: int) -> str:
    if n == 1:
        return ("*Урок 1 из 3:* Что такое P2P в 2025 году и почему это возможность, которую нельзя пропустить. 💡\n\n"
                "Без воды: базовые принципы, где и как начать. После урока — первые шаги.")
    if n == 2:
        return ("*Урок 2 из 3:* Как я заработал $50 000 и новый Mercedes за 3 месяца. 🚀")
    return ("*Урок 3 из 3:* Связка на Р2Р: быстрый путь к первому профиту. 💸")
# ========= TEXTS =========
WELCOME_LONG = (
    "Привет✌️\n\n"
    "У меня для тебя *подарок* — сразу *3 бесплатных урока по P2P* 🤝\n\n"
    "Я *Стас Грибовский*, эксперт в сфере Р2Р уже более 3 лет!\n"
    "Тут тебя ждет *интенсив по Р2Р арбитражу* 🚀\n\n"
    "Наша цель — понять *основу Р2Р* и выйти на *свой первый доход* в этой сфере!\n"
    "Я собрал для тебя *практику и реальные кейсы*: шаг за шагом покажу, как работает P2P и доведу тебя до *первого результата*!\n\n"
    "👉 В последнем уроке тебя ждет *связка*, применив которую ты выйдешь на свой *первый доход в Р2Р*.\n\n"
    "Поэтому, выдели время, налей чашечку чая, устройся поудобнее и *начинаем*!\n\n"
    "✅ *В интенсиве тебя ждут 3 бесплатных урока:*\n"
    "1️⃣ *Что такое P2P в 2025 году* и почему это возможность, которую нельзя пропустить.\n"
    "2️⃣ *Как я заработал $50 000 и новый Mercedes* за 3 месяца\n"
    "3️⃣ *Связка на Р2Р: 60$ за два часа*"
)
LESSON1_INTRO = (
    "Сейчас перед тобой будет первый урок по P2P-арбитражу, *который я подготовил именно для тебя.*\n\n"
    "В нём ты узнаешь:\n"
    "• что такое P2P и как это работает;\n"
    "• как P2P существовало ещё тысячи лет назад и почему это вечная профессия;\n"
    "• что нужно, чтобы начать зарабатывать на P2P.\n\n"
    "А ещё я подготовил для тебя крутой бонус 🎁 — ты получишь его после просмотра всех трёх уроков.\n"
    "Поэтому не откладывай на потом и приступай к просмотру прямо сейчас!\n\n"
    "Готов начинать?"
)
AFTER_L1 = (
    "*Ты большой молодец, что посмотрел первый урок!* 🙌\n\n"
    "Я вложил в него много усилий и надеюсь, что он был для тебя полезен. "
    "Буду рад, если ты напишешь мне отзыв в [Instagram](https://www.instagram.com/grybovskystas_/) и поделишься своими впечатлениями после просмотра.\n\n"
    "А теперь не будем тянуть — держи доступ ко второму уроку 🚀\n"
    "Напоминаю: в третьем уроке я раскрою схему, которую ты сможешь внедрить в свою работу и зарабатывать от 800$ в месяц!\n\n"
    "Нажимай на кнопку ниже и приступай к просмотру 👀"
)

AFTER_L2 = (
    "Большая часть нашего интенсива уже позади 🔥\n\n"
    "Сейчас тебя ждёт *третий, заключительный урок*, в котором я покажу схему, на которой *на твоих глазах* "
    "сделаю *+2%* к начальному депозиту всего за несколько минут. И да — позже ты сможешь *просто повторять за мной те же самые шаги!*\n\n"
    "Не откладывай на потом — изучи эту связку прямо сейчас. *Жми на кнопку ниже и получай доступ* 👇"
)
GATE_BEFORE_L3 = (
    "Так же, по секрету, хочу с тобой поделиться: *я веду дневник, в котором пишу пост каждый вечер*. \n"
    "Там я делюсь *полезными инсайтами, бизнес-советами, своими мыслями и даю ценные рекомендации*.\n\n"
    "Некоторое время назад я поставил себе цель — *купить новый Mercedes AMG с нуля всего за 180 дней* 🔥\n"
    "*Я не знаю, получится ли у меня, но ты можешь стать частью этого*.\n\n"
    "Также ты можешь легко заработать: *если заметишь, что я не выложил пост в какой-то из дней - напиши мне об этом лично, и я скину тебе 50$*.\n\n"
    "Чтобы получить *третий урок*, в котором я раскрою все секреты связки, на которой заработал и продолжаю зарабатывать до сих пор, *подпишись на мой дневник* 👇"
)

BLOCK_6 = ""
BLOCK_7 = ""

# ========= ДОСТУП/НАПОМИНАНИЯ =========
ACCESS_NUDGE_TEXTS = [
    "Вижу, ты ещё не забрал доступ к урокам. Нажми ниже — начнём с первого 👇",
    "Напомню про интенсив: 3 бесплатных урока ждут тебя. Забери доступ 👇",
    "Давай не откладывать — забирай доступ и стартуем прямо сейчас 👇",
]
 # === Рассылка 8 постов по 1 каждые 5 часов ===
def kb_course() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔥 Мини курс Р2Р", callback_data="buy_course"))
    return kb.as_markup()



async def _send_file_with_fallback(chat_id: int, file_path_or_id: str, caption: str | None = None, reply_markup=None):
    """
    Отправляет файл, используя локальный путь (если существует) или file_id.
    """
    if not file_path_or_id:
        logging.warning("_send_file_with_fallback: empty file_path_or_id for chat %s", chat_id)
        return "no_file_id"

    # 1. Проверяем, является ли строка путем к СУЩЕСТВУЮЩЕМУ файлу
    resolved_file_path = file_path_or_id
    logging.info("DEBUG: file_path_or_id = %s", file_path_or_id)
    # If it's a simple filename and not an absolute path, assume it's in the videos directory
    if not Path(file_path_or_id).is_absolute() and not ("/" in file_path_or_id or "\\" in file_path_or_id):
        potential_video_path = BASE_DIR / "videos" / file_path_or_id
        logging.info("DEBUG: potential_video_path = %s", potential_video_path)
        if potential_video_path.is_file():
            resolved_file_path = str(potential_video_path)
    elif not Path(file_path_or_id).is_absolute() and (BASE_DIR / file_path_or_id).is_file():
        resolved_file_path = str(BASE_DIR / file_path_or_id)
    logging.info("DEBUG: resolved_file_path = %s", resolved_file_path)

    if Path(resolved_file_path).is_file():
        try:
            video = FSInputFile(resolved_file_path)
            await bot.send_video(chat_id, video, caption=caption, reply_markup=reply_markup)
            logging.info("Sent local video file %s to chat %s", resolved_file_path, chat_id)
            return "local_video"
        except TelegramEntityTooLarge as e:
            logging.warning("Local video file %s to chat %s is too large for direct video send. Attempting to send as document. Error: %s", resolved_file_path, chat_id, e)
            try:
                document = FSInputFile(resolved_file_path)
                await bot.send_document(chat_id, document, caption=caption, reply_markup=reply_markup)
                logging.info("Sent local video file %s as document to chat %s", resolved_file_path, chat_id)
                return "local_document"
            except Exception as doc_e:
                logging.exception("Failed to send local video file %s as document to chat %s: %s", resolved_file_path, chat_id, doc_e)
                return "failed_local_document"
            except TelegramForbiddenError:
                logging.warning("TelegramForbiddenError when sending local video file %s to chat %s. User may have blocked the bot.", resolved_file_path, chat_id)
                return "forbidden_local_video"
            except Exception as e:
                logging.exception("Failed to send local video file %s as document to chat %s: %s", resolved_file_path, chat_id, e)
                return "failed_local_document"
        except TelegramForbiddenError:
            logging.warning("TelegramForbiddenError when sending local video file %s to chat %s. User may have blocked the bot.", resolved_file_path, chat_id)
            return "forbidden_local_video"
        except Exception as e:
            logging.exception("Failed to send local video file %s to chat %s: %s", resolved_file_path, chat_id, e)
            return "failed_local_video"
    # 2. Если файл по такому пути не найден, проверяем, похожа ли строка на путь.
    # Если да, то это ошибка конфигурации, и не нужно пытаться отправить ее как file_id.
    is_path_like = "/" in resolved_file_path or "\\" in resolved_file_path
    if is_path_like:
        logging.error("File not found at path: '%s'. Cannot send to chat %s.", resolved_file_path, chat_id)
        return "file_not_found"

    # 3. Если это не путь к файлу, считаем, что это file_id и пытаемся отправить.
    file_id = file_path_or_id
    logging.info("DEBUG: Attempting to send as file_id: %s", file_id)
    try:
        # Попытка №1: отправить как video_note, если похоже
        if _looks_like_videonote(file_id):
            try:
                await bot.send_video_note(chat_id, file_id)
                logging.info("Sent as video_note (file_id) to chat %s", chat_id)
                if caption or reply_markup:
                    await bot.send_message(chat_id, caption or " ", reply_markup=reply_markup)
                return "video_note"
            except TelegramBadRequest:
                logging.warning("Failed to send %s as video_note, trying as video.", file_id)
            except TelegramForbiddenError:
                logging.warning("TelegramForbiddenError when sending %s as video_note to chat %s. User may have blocked the bot.", file_id, chat_id)
                return "forbidden_video_note"

        # Попытка №2: отправить как обычное видео
        await bot.send_video(chat_id, file_id, caption=caption, reply_markup=reply_markup)
        logging.info("Sent as video (file_id) to chat %s", chat_id)
        return "video"

    except TelegramForbiddenError:
        logging.warning("TelegramForbiddenError when sending file_id %s as video to chat %s. User may have blocked the bot.", file_id, chat_id)
        return "forbidden_video"
    except TelegramBadRequest as e:
        # Ловим конкретную ошибку, чтобы не отправлять пользователю неверный ID
        if "wrong file identifier" in str(e) or "wrong HTTP URL specified" in str(e):
            logging.error("Invalid file_id or URL: '%s' for chat %s. Error: %s", file_id, chat_id, e)
            return "invalid_file_id"
        else:
            logging.exception("Telegram API error sending file_id %s to chat %s: %s", file_id, chat_id, e)
            return "failed_telegram_error"
    except Exception as e:
        logging.exception("Unexpected error sending file_id %s to chat %s: %s", file_id, chat_id, e)
        return "failed_unexpected"

async def send_course_posts(chat_id: int):
    if chat_id in SENDING_POSTS:
        return
    SENDING_POSTS.add(chat_id)
    set_loop_stopped(chat_id, False)
    await asyncio.sleep(60*60*5)

    posts_list = list(enumerate(COURSE_POSTS, start=1))

    while not is_loop_stopped(chat_id):
        random.shuffle(posts_list)
        for i, text in posts_list:
            if is_loop_stopped(chat_id):
                break
            try:
                logging.info("Отправляем пост %s", i)

                reply_markup = kb_course()  # Default keyboard
                if i in [3, 4]:
                    stage = get_stage(chat_id)
                    if stage < 3:
                        next_lesson = stage + 1
                        reply_markup = kb_open(next_lesson)

                # Посты с видео
                if i in COURSE_POST_VIDEOS:
                    video_path = COURSE_POST_VIDEOS[i]
                    caption = text[:1024]
                    await _send_file_with_fallback(chat_id, video_path, caption, reply_markup=reply_markup)
                # Посты с фото/баннерами
                elif i in COURSE_POST_MEDIA:
                    media = COURSE_POST_MEDIA[i]
                    if isinstance(media, str):  # banner
                        caption = text[:1024]
                        try:
                            await bot.send_photo(chat_id, media, caption=caption, reply_markup=reply_markup)
                        except Exception as e:
                            logging.warning("Failed to send banner %s: %s", media, e)
                            await bot.send_message(chat_id, text, reply_markup=reply_markup)
                    elif isinstance(media, list):  # list of photo indices
                        if len(media) == 1:
                            photo = COURSE_POST_PHOTOS[media[0]]
                            caption = text[:1024]
                            await bot.send_photo(chat_id, photo, caption=caption, reply_markup=reply_markup)
                        elif len(media) > 1:
                            # send media group as gallery
                            media_group = [InputMediaPhoto(media=COURSE_POST_PHOTOS[idx]) for idx in media]
                            media_group[0].caption = text[:1024]
                            await bot.send_media_group(chat_id, media_group)
                            # Manually send a follow-up message with the keyboard for media groups
                            await bot.send_message(chat_id, "👇", reply_markup=reply_markup)

                else:
                    await bot.send_message(chat_id, text, reply_markup=reply_markup)
            except Exception as e:
                logging.warning("Failed to send course post %s: %s", i, e)
            await asyncio.sleep(60*60*5)  # 5 часов между постами

    logging.info("Post loop stopped for user %d", chat_id)
    if chat_id in SENDING_POSTS:
        SENDING_POSTS.remove(chat_id)

async def access_nurture(user_id: int):
    """Спам до нажатия «ПОЛУЧИТЬ ДОСТУП». Запускать после /start."""
    for i, delay in enumerate(ACCESS_REM_DELAYS):
        await asyncio.sleep(delay)
        if get_stage(user_id) >= 1:
            break
        txt = ACCESS_NUDGE_TEXTS[min(i, len(ACCESS_NUDGE_TEXTS) - 1)]
        try:
            await bot.send_message(user_id, txt, reply_markup=kb_access())
        except TelegramForbiddenError:
            break
        except Exception as e:
            logging.warning("PM access nudge failed: %s", e)
            break

async def remind_if_not_opened(user_id: int, stage_expected: int, delay: int):
    """Напоминаем открыть урок stage_expected, если через delay он не открыт."""
    await asyncio.sleep(delay)
    if get_stage(user_id) < stage_expected:
        texts = {
            1: "Вижу, ты ещё не открыл *первый бесплатный урок*. Забирай его сейчас 👇",
            2: "Напомню: *урок 2* всё ещё ждёт тебя.👇",
            3: "Остался *урок 3*. Давай доведём до результата 💸👇",
        }
        try:
            await bot.send_message(user_id, texts[stage_expected], reply_markup=kb_open(stage_expected))
        except Exception as e:
            logging.warning("PM reminder failed: %s", e)

# ========= HANDLERS =========

async def start_welcome_sequence(chat_id: int):
    """Sends the full welcome message sequence."""
    set_stage(chat_id, 0)
    set_pm_ok(chat_id, True)
    # Отправляем первый блок без кнопки
    await send_block(chat_id, BANNER_WELCOME, WELCOME_LONG)
    await asyncio.sleep(22)  # небольшая пауза
    # Отправляем новый блок с описанием урока и кнопкой
    await send_block(chat_id, BANNER_AFTER4, LESSON1_INTRO, reply_markup=kb_access())
    asyncio.create_task(send_course_posts(chat_id))

@router.message(Command("start"))
async def on_start(m: Message):
    await start_welcome_sequence(m.from_user.id)


@router.callback_query(F.data == "buy_course")
async def on_buy_course(cb: CallbackQuery):
    await cb.answer("Открываю ссылку на курс...")
    set_loop_stopped(cb.from_user.id, True)
    await cb.message.answer(f"Вот ссылка на курс: {SITE_URL}")


@router.callback_query(F.data.startswith("open:"))

async def on_open(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)

    try:
        n = int(cb.data.split(":")[1])
    except Exception:
        return

    uid = cb.from_user.id

    if n == 3:
        await send_block(cb.message.chat.id, BANNER_AFTER2, GATE_BEFORE_L3, reply_markup=kb_subscribe_then_l3())


    URLS = {1: LESSON1_URL, 2: LESSON2_URL}
    if n != 3:
        await send_url_only(cb.message.chat.id, URLS[n])

    stage = get_stage(uid)
    if n > stage:
        set_stage(uid, n)

    # Урок 1 и 2 → автопереход
    if n in (1, 2):
        asyncio.create_task(auto_send_next_lesson(uid, n))

    # Урок 3 → блоки и рассылка постов
    if n == 3:
        # файл уже отправили выше; только блоки/рассылка
        async def delayed_blocks(chat_id: int):

            await _send_file_with_fallback(chat_id, LESSON3_ADDITIONAL_VIDEO_FILE, None)

        asyncio.create_task(delayed_blocks(cb.message.chat.id))
        asyncio.create_task(send_course_posts(cb.message.chat.id))

@router.message(F.video_note)
async def capture_video_note(m: Message):
    fid = m.video_note.file_id
    await m.reply(f"Captured video_note file_id:\n<code>{fid}</code>\nlen={len(fid)}", parse_mode=ParseMode.HTML)
    # сохранить в stats.json для удобства (для L3_FOLLOWUP_FILE)
    d = _read()
    d.setdefault("meta", {})["L3_FOLLOWUP_FILE"] = fid
    _write(d)
    logging.info("Captured and saved L3_FOLLOWUP_FILE as file_id=%s", fid)
    await m.reply("Сохранил file_id в store (stats.json). Теперь можно использовать /test_l3.", parse_mode=None)
@router.callback_query(F.data == "check_diary")
async def check_diary(cb: CallbackQuery):
    await cb.answer()
    # Убираем кнопки после нажатия
    await cb.message.edit_reply_markup(reply_markup=None)
    
    uid = cb.from_user.id

    if DIARY_TG_CHAT_ID and has_diary_request(uid):
        # Отправляем файл L3_FOLLOWUP_FILE
        await _send_file_with_fallback(cb.message.chat.id, L3_FOLLOWUP_FILE, None)
        # Отправляем ссылку на 3 урок
        URLS = {1: LESSON1_URL, 2: LESSON2_URL, 3: LESSON3_URL}
        await send_url_only(cb.message.chat.id, URLS[3])
    else:
        txt = (
            "Пока не вижу твою заявку в дневник.\n"
            "Нажми «Подписаться на дневник», отправь запрос и затем снова жми «ПРОВЕРИТЬ»."
        )
        await cb.message.answer(txt, reply_markup=kb_subscribe_then_l3())

@router.chat_join_request()
async def on_join_request(req: ChatJoinRequest):
    uid = req.from_user.id

    # если это твой ДНЕВНИК (канал с заявками)
    if DIARY_TG_CHAT_ID and req.chat.id == DIARY_TG_CHAT_ID:
        await req.approve()
        logging.info("Silently approved diary join request for user %s in chat %s", uid, req.chat.id)
        set_diary_request(uid, True)
        return

    # For all other channels, approve and try to start the full welcome sequence.
    await req.approve()
    logging.info(f"Approved join request for user {uid} in chat {req.chat.id}.")
    try:
        logging.info(f"Attempting to proactively start welcome sequence for user {uid}.")
        await start_welcome_sequence(uid)
        logging.info(f"Successfully started welcome sequence for user {uid}.")
    except TelegramForbiddenError:
        logging.warning(f"Cannot send proactive message to user {uid}. They must start the bot manually.")
    except Exception as e:
        logging.error(f"An unexpected error occurred in on_join_request for user {uid}: {e}")


@router.message(Command("test_l3"))
async def test_l3(m: Message):
    file_or_id = L3_FOLLOWUP_FILE
    if not file_or_id:
        return await m.answer("L3_FOLLOWUP_FILE порожній у .env", parse_mode=None)
    try:
        result = await _send_file_with_fallback(m.chat.id, file_or_id, L3_FOLLOWUP_CAPTION or None)
        await m.answer(f"Результат отправки: {result}", parse_mode=None)
    except Exception as e:
        logging.exception("test_l3 failed: %s", e)
        await m.answer(f"❌ Не вдалося надіслати: {e}", parse_mode=None)

@router.message(F.forward_from_chat)
async def on_forwarded_from_channel(message: Message):
    ch = message.forward_from_chat
    await message.answer(
        f"Название: {ch.title}\nID: <code>{ch.id}</code>"
    )

@router.message(Command("diag"))
async def diag(m: Message):
    me = await bot.get_me()
    await m.answer(
        f"*Diag*\nBot: @{me.username}\nDEEP_LINK: {DEEP_LINK}\n"
        f"REM1/2/3={REM1_DELAY}/{REM2_DELAY}/{REM3_DELAY}\n"
        f"NEXT_AFTER_1/2={NEXT_AFTER_1}/{NEXT_AFTER_2}",
        parse_mode=ParseMode.MARKDOWN
    )

@router.message(Command("stats"))
async def stats(m: Message):
    if ADMIN_ID and m.from_user.id != ADMIN_ID:
        return
    d = _read()
    await m.answer(f"Users tracked: {len(d.get('users', {}))}")

def extract_file_id(msg: Message):
    ct = msg.content_type
    if ct == ContentType.PHOTO and msg.photo:
        return msg.photo[-1].file_id, ct
    if ct == ContentType.DOCUMENT and msg.document:
        return msg.document.file_id, ct
    if ct == ContentType.VIDEO and msg.video:
        return msg.video.file_id, ct
    if ct == ContentType.AUDIO and msg.audio:
        return msg.audio.file_id, ct
    if ct == ContentType.VOICE and msg.voice:
        return msg.voice.file_id, ct
    if ct == ContentType.VIDEO_NOTE and msg.video_note:
        return msg.video_note.file_id, ct
    if ct == ContentType.STICKER and msg.sticker:
        return msg.sticker.file_id, ct
    if ct == ContentType.ANIMATION and msg.animation:
        return msg.animation.file_id, ct
    return None, ct

@router.message()
async def any_dm_message(message: Message):
    fid, ct = extract_file_id(message)
    if fid:
        await message.reply(
            f"content_type: <b>{ct}</b>\nfile_id:\n<code>{fid}</code>"
        )
    else:
        await message.reply(f"content_type: <b>{ct}</b>\n(для цього типу немає file_id)")

@router.channel_post()
async def any_channel_post(message: Message):
    fid, ct = extract_file_id(message)
    if fid:
        await message.reply(
            f"content_type: <b>{ct}</b>\nfile_id:\n<code>{fid}</code>"
        )
    else:
        await message.reply(f"content_type: <b>{ct}</b>\n(немає file_id)")

# ========= WEBHOOK INFRASTRUCTURE =========

async def on_startup(app: web.Application):
    """Set webhook on startup"""
    await bot.delete_webhook(drop_pending_updates=True)
    if not EXTERNAL_URL:
        raise RuntimeError("External URL is required for webhook mode. Platform should provide RENDER_EXTERNAL_URL, RAILWAY_STATIC_URL, or REPLIT_DEV_DOMAIN.")
    webhook_url = f"{EXTERNAL_URL}/webhook/{WEBHOOK_SECRET}"
    await bot.set_webhook(
        url=webhook_url,
        secret_token=WEBHOOK_SECRET,
    )
    logging.info("Webhook set to: %s", webhook_url)

async def on_shutdown(app: web.Application):
    """Clean up on shutdown"""
    await bot.session.close()

async def handle_webhook(request: web.Request):
    """Handle incoming webhook requests from Telegram"""
    if request.match_info.get("token") != WEBHOOK_SECRET:
        return web.Response(status=403)
    
    try:
        data = await request.json()
        update = Update.model_validate(data)
        dp = request.app["dp"]
        await dp.feed_update(bot, update)
        return web.Response(text="OK")
    except Exception as e:
        logging.error("Webhook error: %s", e)
        return web.Response(status=500)

def make_web_app():
    """Create and configure the web application"""
    app = web.Application()
    dp = Dispatcher()
    dp.include_router(router)
    app["dp"] = dp
    
    # Add webhook route
    app.router.add_post(f"/webhook/{{token}}", handle_webhook)
    
    # Add lifecycle handlers
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    
    return app

async def run_polling():
    """Run bot in polling mode"""
    dp = Dispatcher()
    dp.include_router(router)
    
    try:
        await bot.delete_webhook(drop_pending_updates=True)
    except Exception:
        pass
    
    logging.info("Starting bot in polling mode...")
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

async def main():
    """Initialize bot and set deep link"""
    global DEEP_LINK
    me = await bot.get_me()
    DEEP_LINK = f"https://t.me/{me.username}?start=from_channel"
    logging.info("Bot: @%s, Deep-link: %s", me.username, DEEP_LINK)

async def run_webhook():
    """Run webhook server for production"""
    logging.info("Running in webhook mode on port %s", PORT)
    global DEEP_LINK
    me = await bot.get_me()
    DEEP_LINK = f"https://t.me/{me.username}?start=from_channel"
    logging.info("Bot: @%s, Deep-link: %s", me.username, DEEP_LINK)
    
    app = make_web_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="0.0.0.0", port=PORT)
    await site.start()
    
    logging.info("Webhook server started on 0.0.0.0:%s", PORT)
    # Keep the server running
    try:
        await asyncio.Future()  # run
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    if RUN_MODE.lower() == "polling":
        logging.info("Running in polling mode")
        asyncio.run(run_polling())
    else:
        asyncio.run(run_polling())
