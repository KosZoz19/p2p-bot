import asyncio
import json
import os
import logging
import random
from pathlib import Path
from time import time
from typing import Dict, Any
from aiogram.types import Update, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, InputMediaVideo, InputFile
from aiogram.enums.chat_member_status import ChatMemberStatus
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode, ContentType
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup,
    InlineKeyboardButton, ChatJoinRequest, InputMediaPhoto, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramEntityTooLarge
from aiogram.utils.media_group import MediaGroupBuilder
from dotenv import load_dotenv
from aiohttp import web
from aiogram import Bot, Dispatcher, Router, F

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

WELCOME_VIDEO_FILE = os.getenv("WELCOME_VIDEO_FILE", "videos/welcome.mp4")  # e.g., "videos/welcome.mp4"

L3_FOLLOWUP_VIDEO = os.getenv("L3_FOLLOWUP_VIDEO", "")
L3_FOLLOWUP_CAPTION = os.getenv("L3_FOLLOWUP_CAPTION", "")
L3_FOLLOWUP_DELAY = int(os.getenv("L3_FOLLOWUP_DELAY", "5"))
# Теперь используем путь к файлу или file_id из .env
raw_l3 = os.getenv("L3_FOLLOWUP_FILE", "") or ""
L3_FOLLOWUP_FILE = raw_l3.strip().replace("\u200b", "").replace("\ufeff", "").replace("\u2060", "")
if L3_FOLLOWUP_FILE == "":
    L3_FOLLOWUP_FILE = ""

DIARY_TG_CHAT_ID = int(os.getenv("DIARY_TG_CHAT_ID", "0") or 0)
DIARY_TG_JOIN_URL = os.getenv("DIARY_TG_JOIN_URL", "")
DIARY_URL = os.getenv("DIARY_URL", "https://instagram.com/your_diary_here")
FORM_URL = os.getenv("FORM_URL", "https://docs.google.com/forms/d/e/1FAIpQLSfFZkXzO7DwoCFZRN-u_4iR6xEQRfaOSlKX9b5AnVRzEkZ7fw/viewform?usp=header")

# задержки напоминаний
REM1_DELAY = int(os.getenv("REM1_DELAY", "60"))
REM2_DELAY = int(os.getenv("REM2_DELAY", "300"))
REM3_DELAY = int(os.getenv("REM3_DELAY", "600"))

# быстрые паузы для следующего тизера (после клика по текущему уроку)
NEXT_AFTER_1 = int(os.getenv("NEXT_AFTER_1", "1800"))  # 30 minutes
NEXT_AFTER_2 = int(os.getenv("NEXT_AFTER_2", "1800"))  # 30 minutes

# напоминалки до нажатия «ПОЛУЧИТЬ ДОСТУП»
ACCESS_REM_DELAYS = [
    int(x) for x in os.getenv("ACCESS_REM_DELAYS", "120,300,900").split(",")
    if x.strip().isdigit()
]

COURSE_POST_DELAY = int(os.getenv("COURSE_POST_DELAY", "1800"))
ROTATION_DELAY = int(os.getenv("ROTATION_DELAY", "21600"))
LAST_BOT_MESSAGE_TS: dict[int, float] = {}

MARK_REMIND_DELAY_1 = int(os.getenv("MARK_REMIND_DELAY_1", "300"))
MARK_REMIND_DELAY_2 = int(os.getenv("MARK_REMIND_DELAY_2", "300"))

ADMIN_ID = int(os.getenv("ADMIN_ID", "0") or 0)

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))

async def send_admin_message(text: str):
    """Send a message to the admin if ADMIN_ID is set."""
    if ADMIN_ID:
        try:
            await bot.send_message(ADMIN_ID, text)
        except Exception as e:
            logging.error("Failed to send admin message: %s", e)
router = Router()
DEEP_LINK = ""  # заполним в main()
SENDING_POSTS: set[int] = set()  # chat_ids that are already sending course posts
VIDEO_NOTE_SENT: set[int] = set()

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

def is_first_rotation_done(uid: int) -> bool:
    d = _read()
    return bool(d.get("users", {}).get(str(uid), {}).get("first_rotation_done", False))

def set_first_rotation_done(uid: int, done: bool = True):
    d = _read()
    u = d.setdefault("users", {}).setdefault(str(uid), {})
    u["first_rotation_done"] = bool(done)
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

def _mark_bot_sent(chat_id: int):
    LAST_BOT_MESSAGE_TS[chat_id] = time()

async def _wait_quiet_since_last_bot_message(chat_id: int, delay: int):
    while True:
        last = LAST_BOT_MESSAGE_TS.get(chat_id, 0)
        passed = time() - last
        remaining = delay - passed
        if remaining <= 0:
            return
        await asyncio.sleep(min(5, max(1, int(remaining))))

def smart_truncate(text: str, max_length: int = 700) -> tuple[str, str]:
    """Truncate text intelligently to max_length, preferring sentence boundaries.
    Returns (truncated_text, remainder)"""
    if len(text) <= max_length:
        return text, ""

    # Look for sentence endings within the limit
    sentence_endings = ['. ', '! ', '? ']
    best_pos = -1
    for ending in sentence_endings:
        pos = text.rfind(ending, 0, max_length)
        if pos > best_pos:
            best_pos = pos + len(ending)  # Include the space

    if best_pos > 0:
        truncated = text[:best_pos].rstrip()
        remainder = text[best_pos:].lstrip()
        return truncated, remainder

    # If no sentence ending, try word boundary
    pos = text.rfind(' ', 0, max_length)
    if pos > 0:
        truncated = text[:pos]
        remainder = text[pos:].lstrip()
        return truncated, remainder

    # Last resort: hard truncate
    truncated = text[:max_length-3] + "..."
    remainder = text[max_length-3:]
    return truncated, remainder

async def send_block(chat_id: int, banner_url: str, text: str,
                      reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    try:
        if banner_url:
            # Check if it's a local file path (not a URL)
            if not banner_url.startswith(('http://', 'https://')):
                # It's a local file, use FSInputFile
                try:
                    photo = FSInputFile(banner_url)
                    await bot.send_photo(chat_id, photo, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                    _mark_bot_sent(chat_id)
                    return
                except Exception as e:
                    logging.warning("Failed to send local image %s: %s, falling back to text message", banner_url, e)
                    await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
                    _mark_bot_sent(chat_id)
                    return

            # It's a URL, send as before
            await bot.send_photo(chat_id, banner_url, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            _mark_bot_sent(chat_id)
        else:
            await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
            _mark_bot_sent(chat_id)
    except TelegramBadRequest as e:
        if "wrong type of the web page content" in str(e) or "failed to get HTTP URL content" in str(e):
            logging.warning("Banner URL '%s' rejected by Telegram. Trying to extract direct image URL from Imgur album for chat %s...", banner_url, chat_id)
            # Try to convert Imgur album URL to direct image URL
            if "imgur.com/a/" in banner_url:
                # Extract album ID and try common image extensions
                album_id = banner_url.split("/a/")[-1].split("?")[0].split("#")[0]
                direct_url = f"https://i.imgur.com/{album_id}.jpg"
                try:
                    await bot.send_photo(chat_id, direct_url, caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
                    _mark_bot_sent(chat_id)
                    logging.info("Successfully sent direct image URL %s for chat %s", direct_url, chat_id)
                    return
                except Exception:
                    pass
            logging.warning("Could not extract direct image URL, falling back to text message for chat %s", chat_id)
            await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
            _mark_bot_sent(chat_id)
        else:
            logging.exception("TelegramBadRequest in send_block for chat %s: %s", chat_id, e)
    except TelegramForbiddenError:
        logging.warning("TelegramForbiddenError in send_block for chat %s. User may have blocked the bot.", chat_id)
    except Exception:
        logging.exception("Unexpected error in send_block for chat %s", chat_id)


async def send_url_only(chat_id: int, url: str, reply_markup=None):
    """Отправить только ссылку (без текста)"""
    try:
        await bot.send_message(chat_id, url, reply_markup=reply_markup, disable_web_page_preview=False)
        _mark_bot_sent(chat_id)
    except Exception:
        await bot.send_message(chat_id, url, reply_markup=reply_markup)
        _mark_bot_sent(chat_id)

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
    """Автоматически отправляет следующий урок после небольшой паузы."""
    delay = 0
    if current_lesson == 1:
        delay = NEXT_AFTER_1
    elif current_lesson == 2:
        delay = NEXT_AFTER_2

    if delay > 0:
        await asyncio.sleep(delay)

    try:
        # Failsafe: if user has already advanced, don't send a delayed message for a past lesson
        if get_stage(user_id) > current_lesson:
            logging.info(f"auto_send_next_lesson: User {user_id} is already at stage {get_stage(user_id)}, skipping message for lesson {current_lesson + 1}.")
            return

        if current_lesson == 1:
            # После урока 1 -> отправляем блок и доступ к уроку 2
            await send_block(user_id, BANNER_AFTER3, AFTER_L1, reply_markup=kb_open(2), parse_mode=ParseMode.HTML)
        elif current_lesson == 2:
            # После урока 2 -> отправляем блок перед уроком 3
            await send_block(user_id, BANNER_AFTER5, AFTER_L2, reply_markup=kb_open(3), parse_mode=ParseMode.HTML)

    except Exception as e:
        logging.warning("auto_send_next_lesson failed: %s", e)



async def delete_message_after_delay(chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await bot.delete_message(chat_id, message_id)
    except Exception as e:
        logging.warning(f"Failed to delete message {message_id} in chat {chat_id}: {e}")

# ========= KEYBOARD FUNCTIONS =========
def kb_access() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="🔑 ПОЛУЧИТЬ ДОСТУП", callback_data="open:1"))
    return kb.as_markup()

def kb_access_reply() -> ReplyKeyboardMarkup:
    kb = ReplyKeyboardBuilder()
    kb.add(KeyboardButton(text="🔑 ПОЛУЧИТЬ ДОСТУП"))
    kb.adjust(1)
    return kb.as_markup(resize_keyboard=True)

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
    kb.row(InlineKeyboardButton(text="Мини курс", callback_data="buy_course"))
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
    "Сейчас перед тобой будет первый урок по P2P-арбитражу, <b>который я подготовил именно для тебя.</b>\n\n"
    "В нём ты узнаешь:\n"
    "• что такое P2P и как это работает;\n"
    "• как P2P существовало ещё тысячи лет назад и почему это вечная профессия;\n"
    "• что нужно, чтобы начать зарабатывать на P2P.\n\n"
    "А ещё я подготовил для тебя крутой бонус 🎁 — ты получишь его после просмотра всех трёх уроков.\n"
    "<blockquote>Поэтому не откладывай на потом и приступай к просмотру прямо сейчас!</blockquote>\n\n"
    "Готов начинать?"
)
AFTER_L1 = (
    "<b>Ты большой молодец, что посмотрел первый урок!</b> 🙌\n\n"
    "<i>Я вложил в него много усилий и надеюсь, что он был для тебя полезен.</i>\n\n"
    "Буду рад, если ты напишешь мне отзыв в <a href=\"https://www.instagram.com/grybovsky?igsh=MTNnZnN3NGs3bm5lNw==\">Instagram</a> и поделишься своими впечатлениями после просмотра.\n\n"
    "А теперь не будем тянуть — держи доступ ко второму уроку 🚀\n"
    "Напоминаю: в третьем уроке я раскрою схему, которую ты сможешь внедрить в свою работу и зарабатывать от 800$ в месяц!\n\n"
    "Нажимай на кнопку ниже и приступай к просмотру 👀"
)

AFTER_L2 = (
    "Большая часть нашего интенсива уже позади 🔥\n\n"
    "<i>Сейчас тебя ждёт третий, заключительный урок, в котором я покажу схему, на которой на твоих глазах</i> "
    "<i>сделаю +2% к начальному депозиту всего за несколько минут. И да — позже ты сможешь просто повторять за мной те же самые шаги!</i>\n\n"
    "Не откладывай на потом — изучи эту связку прямо сейчас. <b>Жми на кнопку ниже и получай доступ</b> 👇"
)
GATE_BEFORE_L3 = (
    "Так же, по секрету, хочу с тобой поделиться: <b>я веду дневник, в котором пишу пост каждый вечер</b>. \n"
    "Там я делюсь <b>полезными инсайтами, бизнес-советами, своими мыслями и даю ценные рекомендации</b>.\n\n"
    "Некоторое время назад я поставил себе цель — <b>купить новый Mercedes AMG с нуля всего за 180 дней</b> 🔥\n"
    "<blockquote>Я не знаю, получится ли у меня, но ты можешь стать частью этого.</blockquote>\n\n"
    "Также ты можешь легко заработать: <b>если заметишь, что я не выложил пост в какой-то из дней - напиши мне об этом лично, и я скину тебе 50$</b>.\n\n"
    "<i>Чтобы получить <b>третий урок</b>, в котором я раскрою все секреты связки, на которой заработал и продолжаю зарабатывать до сих пор, <b>подпишись на мой дневник</b></i> 👇"
)


BLOCK_6 = """<b>Хочешь освоить P2P и начать зарабатывать от $100 в день?</b>\n\n
<i>Я представляю тебе мини-курс, в котором:</i>\n
<i>— 5 уроков по 30 минут</i>\n
<i>— рабочая связка которая приносит от 100$ ежедневно. Твоя задача повторять ее за мной и внедрить в свою жизнь</i> \n
<i>— пошаговые инструкции и готовые шаблоны</i>\n
<i>— бонус — промокод на $100 для следующих потоков</i>\n\n
Кол-во мест ограничено⛔️\n\n
Цена 999 грн"""

BLOCK_7 = """Как ты уже понял, <b>у меня есть личное обучение по P2P</b>, которое прошли сотни людей. 
Уникальность программы в том, что все кураторы — это бывшие ученики, а <b>студенты выходят на доход от 1500$ уже в первый месяц после старта.</b> \n\n
<b>Что делает обучение особенным:</b>\n
• Работа в самой безопасной нише в крипте, где ученики зарабатывают до 10% в день.\n
• Более 3 лет моего опыта в сфере, которым я делюсь через самые актуальные знания.\n
• Десятки разных схем и связок по арбитражу: P2P, фандинг, межбиржевой, spot/futures, CEX/DEX. Каждый найдёт то, что подойдёт именно ему.\n
• Уникальное комьюнити, где есть как специалисты из разных областей, так и владельцы крупных компаний.\n\n
<blockquote>И это только часть того, что ждёт внутри — многое остаётся под завесой 😉</blockquote>\n\n
Чтобы попасть в следующий поток, заполняй гугл-форму ниже или связывайся со мной @hrybovsky

https://docs.google.com/forms/d/e/1FAIpQLSfFZkXzO7DwoCFZRN-u_4iR6xEQRfaOSlKX9b5AnVRzEkZ7fw/viewform?usp=header"""

COURSE_POSTS = [
    # Урок 2
    """Я понимаю, что ты очень занят и у тебя много дел, но поверь: после просмотра этого урока ты поймёшь основы P2P и откроешь для себя новую сферу заработка ⏳

Забирай готовый урок по кнопке ниже (доступ ограничен) 👇""",

    # Урок 3
    """Я, конечно, удивлён, почему ты не хочешь получить БЕСПЛАТНО схему, <b>на которой мои ученики зарабатывают в среднем 2500$ в месяц</b>🤔

Ладно, как исключение, даю только тебе доступ к этому уроку, где я раскрыл всю схему.

Забирай по кнопке ниже — <b>урок скоро исчезнет</b>, и ты можешь остаться без доступа 👇""",

    # Пост 1
    BLOCK_6,

    # Пост 2
    """<b>Давай разберём, в чём уникальность этого мини-курса и почему его стоит приобрести</b>

<b>Во-первых</b> — это цена, где ещё ты видел обучение по P2P дешевле 1000 грн
<b>Во-вторых</b> — внутри 5 полноценных уроков по 30 минут каждый
<b>В-третьих</b> — в одном из уроков показана в деталях рабочая связка, на которой я и мои ученики зарабатывают от 100$ ежедневно

Также в курсе ты получишь:
• пошаговый план, как выйти на стабильный доход уже в первый месяц
• разбор частых ошибок новичков, чтобы ты их не допустил
• готовые шаблоны и инструкции для быстрого старта

А ещё в курсе тебя ждёт промокод на 100$ для участия в следующих потоках обучения😉
<blockquote>Когда захочешь присоединиться, просто скажешь кодовое слово с урока и активируешь скидку. Таким образом ты выйдешь в плюс на 80$ (поскольку цена мини курса 20$, а скидка  100$)</blockquote>

<i>Занято 63/100 мест</i>

 А сейчас я даю тебе ссылку на мини-курс, который подготовил специально для тебя 👇""",

    # Пост 3
    BLOCK_7,

    # Пост 4
    """Многие новички которые только заходят в сферу Р2Р думают, что нужно обладать каким-то особым навыком или везением. На самом деле — нет. Всё, что требуется — это желание разобраться и готовность действовать.

На фото выше — отзывы тех, кто пришёл ко мне на обучение. Кто-то делал первые 30-50$ в день. Кто-то закрывал неделю с профитом в $300–400. А те, кто давно начинали уже имеют свои команды и доходы в стабильных несколько тысяч $ каждый месяц.

<blockquote>Вся суть Р2Р это начать с малого, просто чтобы понять и попробовать. А со временем у тебя в руках оказывается инструмент финансовой свободы.Здесь нет потолка, нет ограничений — всё зависит только от того, сколько ты готов вкладывать усилий.</blockquote>

А теперь вопрос к тебе: ты с нами или будешь дальше наблюдать за результатами других и потом жалеть, что не зашёл вовремя?""",

    # Пост 5
    """<b>Сейчас Р2Р для меня - это профессия и основной доход для меня.</b> Но когда я только заходил в эту сферу я ошибочно считал это «темкой» на несколько месяцев

🔷Со временем я понял что Р2Р это далеко не темка а прогнозируемый бизнес на дистанции который дает хорошие результаты. И результат не заставил себя ждать, через какое-то время работы я купил себе Mercedes 

<b>P2P  дало мне свободу.</b>
<blockquote>Где нету начальника, привязанности к месту и потолка дохода. Благодаря Р2Р я могу не переживать о завтрашнем дне и что не менее важно провести его как в Польше так и в Испании</blockquote>

<i>И вот в этом для меня смысл: я нашёл своё дело, которое не привязано ни к конкретной стране, ни к конкретному работодателю. У меня есть ноутбук, телефон и рынок, который работает 24/7.
Кто-то всю жизнь ищет «свою профессию». А я могу сказать честно: я её нашёл. Для меня P2P — это профессия будущего, которая уже сегодня даёт то, к чему многие идут годами: стабильный доход, свободу и независимость</i>""",

    # Пост 6
    """<b>Хороший пример преимущества Р2Р над другими сферами — это полная независимость.</b>

Независимость от всего:

<b>• Время</b>: Не хочешь или не можешь работать днём — работаешь ночью.

<b>• Место</b>: Не хочешь работать из своего города или страны? Р2Р — это онлайн, работай там, где тебе удобно.

<b>• Люди</b>: Не хочешь начальника? Его не будет. Хочешь команду? Собираешь и управляешь.

<b>• Умения</b>: Боишься, что не разберёшься? Ко мне на обучение приходят люди, у которых нет даже минимального понятия не то что в Р2Р, а в крипте в целом. После месяца обучения их доход вырастает до 1000$+.

<i>На видео сверху хороший пример. Один из учеников решил сделать себе мини-отпуск и поехать на отдых за счёт Р2Р. Итог — за отдых он заработал больше, чем потратил.</i>

<blockquote>Р2Р — это инструмент, который в правильных руках даёт полную свободу и независимость. Вопрос, готов ли ты это взять?</blockquote>""",

    # Пост 7
    """<b>А это пример одного из первых учеников, Богдана.</b>

Богдан до Р2Р работал на заводе в Польше и хотел жениться. По его словам, работа на заводе ему надоела, и он решил, что нужно что-то в жизни менять.

Что сделал Богдан? <i>Он пошёл на моё обучение по Р2Р. Несмотря на то, что он раньше не работал в Р2Р и ему было трудно поначалу, через два месяца Богдан вышел на 2500$+ ежемесячно.Хотя у него не было ни больших денег для оборота, ни знаний в Р2Р.</i>

<blockquote>У него было лишь желание.
Желание научиться и желание заработать денег.</blockquote>

И он смог. Сейчас он может себе позволить и свадьбу на Мадейре, и хорошую жизнь без работы на кого-то.

<blockquote>Если получилось у него — получится и у тебя.</blockquote>""",

    # Пост 8
    """<b>Итак, почему же именно Р2Р, а не другие ниши?</b> 👀

1) <b>Нам не нужно никуда вкладывать деньги и что-то покупать</b>, как в товарном бизнесе. В Р2Р мы наши деньги никуда не деваем — они всегда у нас перед глазами.

2) <b>Р2Р — это бизнес онлайн.</b> Нету привязки ко времени (многие работают в ночное время), к месту и к людям.

3) В Р2Р <b>нет потолка по заработку.</b> Здесь можно масштабироваться и строить свои команды.

4) <b>Не нужно иметь много денег</b> для старта. Достаточно начинать с 300$.

5)<b> Лёгкий старт для новичков.</b> Здесь не нужно учиться годами (в отличие от фьючерсной торговли).

6) Р2Р —<b> сфера без рисков</b>, в отличие от других направлений, связанных с криптовалютой.

<i>Самое важное, что нужно понять новичку: Р2Р — это не «темка», а полноценный бизнес, в который нужно вкладывать силы и время.</i>

<blockquote>Я могу дать тебе все необходимые знания, чтобы ты начал развиваться в этой сфере. Вопрос: готов ли ты их взять?</blockquote>""",

    #Just a video
    "",

    # Пост 9
    """<b>Серафим давно знал о сфере P2P. Он слышал о ней ещё несколько лет назад, но всё это время боялся попробовать — не хватало уверенности и понимания, с чего начать.</b> 

Когда он узнал обо мне, мы пообщались, и я объяснил ему, что в этой сфере нельзя проебаться, если действовать с умом. 

После этого Серафим решился попробовать себя в P2P и четыре месяца назад пришёл ко мне на обучение.

<i>С тех пор он активно работает в этой сфере, совмещая её с учёбой в университете. Ему хватает всего нескольких часов в день, чтобы закрывать ордера — прямо во время пар или занимаясь своими делами. 
За это время он смог встроить P2P в свою повседневную жизнь и добиться стабильных результатов.</i>

<blockquote>А с первых заработанных денег Серафим купил себе <b>новенький iPhone 16 Pro</b>
Р2Р дает не только свободну в плане финансов, а так же и помогает достигать целей</blockquote>""",

    # Пост 10
    """Когда я начинал заниматься Р2Р - был студентом сам. И я лично на своем опыте знаю какого это, учится и быть практически без денег. 

<blockquote>Вариант совмещать Р2Р с учебой очень хороший. Он позволяет каждому учится и паралельно работать в Онлайне и иметь от 1000$+</blockquote>
По поводу обучения Серафим отзывается так :

<blockquote>Поначалу было страшно что не получится и боялся потерять деньги. Со временем, когда уже получил все нужные ответы на свои вопросы - стало полегче и понятнее. С этого момента и понеслась полноценная работа</blockquote>"""
    ]
# New variables for course posts media
COURSE_POST_PHOTOS = [
    "https://files.fm/thumb_show.php?i=y2ptpj6c86",
    "https://files.fm/thumb_show.php?i=y2zug7c57t",
    "https://files.fm/thumb_show.php?i=3zvc6xdxb7",
    "https://files.fm/thumb_show.php?i=tg3eeccayz",
    "https://files.fm/thumb_show.php?i=xda488wd7v",
    "https://files.fm/thumb_show.php?i=sv4yfg58r4",
    "https://files.fm/thumb_show.php?i=ft96sdta7t",
    "https://files.fm/thumb_show.php?i=mdvutpnw27",
    BANNER_BLOCK6,
    BANNER_BLOCK7,
    "https://files.fm/thumb_show.php?i=3z64keef56",
    "https://files.fm/thumb_show.php?i=e45f6vdq3w",
    "https://files.fm/thumb_show.php?i=2xu22t23sa"
]

COURSE_POST_VIDEOS = {
    6: [{
        "path": "videos/post_2.MOV",
        "height": 1280,
        "width": 720,
    }],
    7: [{
        "path": "videos/post_5.MP4",
        "height": 1280,
        "width": 624,
    }],
    9: [{
        "path": "videos/post_7.MOV",
        "height": 1280,
        "width": 720,
    }],
    10: [{
        "path": "videos/just_a_video.MP4",
        "height": 1280,
        "width": 720,
    }],
    11: [
        {
            "path": "videos/post_9_1.MP4",
            "height": 1280,
            "width": 720,
        },
        {
            "path": "videos/post_9_2.MP4",
            "height": 1280,
            "width": 720,
        }
    ],
    12: [
        {
            "path": "videos/post_10.MP4",
            "height": 1280,
            "width": 720,
        },
    ]
}

COURSE_POST_MEDIA = {
    0: [2],  # third photo
    1: [7],  # banner
    2: [8],
    3: [6],  # seventh photo
    4: [9],
    5: [0, 1],  # first two photos
    8: [3, 4, 5],  # fourth, fifth, sixth photos
    11: [10],
    12: [11, 12]
}

# ========= ДОСТУП/НАПОМИНАНИЯ =========
ACCESS_NUDGE_TEXTS = [
    "Вижу, ты ещё не забрал доступ к урокам. Нажми ниже — начнём с первого 👇",
    "Напомню про интенсив: 3 бесплатных урока ждут тебя. Забери доступ 👇",
    "Давай не откладывать — забирай доступ и стартуем прямо сейчас 👇",
]
 # === Рассылка 8 постов по 1 каждые 5 часов ===
def kb_course() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Получить доступ", url=SITE_URL))
    return kb.as_markup()

def kb_course_2() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.row(InlineKeyboardButton(text="Мини курс по P2P", url=SITE_URL))
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
            _mark_bot_sent(chat_id)
            logging.info("Sent local video file %s to chat %s", resolved_file_path, chat_id)
            return "local_video"
        except TelegramEntityTooLarge as e:
            logging.warning("Local video file %s to chat %s is too large for direct video send. Attempting to send as document. Error: %s", resolved_file_path, chat_id, e)
            try:
                document = FSInputFile(resolved_file_path)
                await bot.send_document(chat_id, document, caption=caption, reply_markup=reply_markup)
                _mark_bot_sent(chat_id)
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
                _mark_bot_sent(chat_id)
                logging.info("Sent as video_note (file_id) to chat %s", chat_id)
                if caption or reply_markup:
                    await bot.send_message(chat_id, caption or " ", reply_markup=reply_markup)
                    _mark_bot_sent(chat_id)
                return "video_note"
            except TelegramBadRequest:
                logging.warning("Failed to send %s as video_note, trying as video.", file_id)
            except TelegramForbiddenError:
                logging.warning("TelegramForbiddenError when sending %s as video_note to chat %s. User may have blocked the bot.", file_id, chat_id)
                return "forbidden_video_note"

        # Попытка №2: отправить как обычное видео
        await bot.send_video(chat_id, file_id, caption=caption, reply_markup=reply_markup)
        _mark_bot_sent(chat_id)
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

    try:
        while True:
            stage = get_stage(chat_id)
            if stage < 9 or not is_first_rotation_done(chat_id):
                await _wait_quiet_since_last_bot_message(chat_id, COURSE_POST_DELAY)

            if stage < 2:
                set_stage(chat_id, 2)
                continue

            if stage == 2:
                await send_url_only(chat_id, LESSON1_URL)
                await asyncio.sleep(2)
                await send_block(chat_id, BANNER_AFTER3, AFTER_L1, reply_markup=kb_open(2), parse_mode=ParseMode.HTML)
                _mark_bot_sent(chat_id)
                set_stage(chat_id, 3)
                continue

            if stage == 3:
                await send_block(chat_id, COURSE_POST_PHOTOS[2], COURSE_POSTS[0], reply_markup=kb_open(2), parse_mode=ParseMode.HTML)
                _mark_bot_sent(chat_id)
                set_stage(chat_id, 4)
                continue

            if stage == 4:
                await send_url_only(chat_id, LESSON2_URL)
                await asyncio.sleep(2)
                await send_block(chat_id, BANNER_AFTER5, AFTER_L2, reply_markup=kb_open(3), parse_mode=ParseMode.HTML)
                _mark_bot_sent(chat_id)
                set_stage(chat_id, 5)
                continue

            if stage == 5:
                await send_block(chat_id, COURSE_POST_PHOTOS[7], COURSE_POSTS[1], reply_markup=kb_open(3), parse_mode=ParseMode.HTML)
                _mark_bot_sent(chat_id)
                set_stage(chat_id, 6)
                continue

            if stage == 6:
                await send_block(chat_id, BANNER_AFTER2, GATE_BEFORE_L3, reply_markup=kb_subscribe_then_l3(), parse_mode=ParseMode.HTML)
                _mark_bot_sent(chat_id)
                set_stage(chat_id, 7)
                continue

            if stage == 7:
                await send_url_only(chat_id, LESSON3_URL)
                _mark_bot_sent(chat_id)
                set_stage(chat_id, 8)
                continue

            if stage == 8:
                if chat_id not in VIDEO_NOTE_SENT:
                    await bot.send_video_note(chat_id, FSInputFile(WELCOME_VIDEO_FILE))
                    _mark_bot_sent(chat_id)
                    VIDEO_NOTE_SENT.add(chat_id)
                set_stage(chat_id, 9)
                continue

            post_indices = [i for i in range(len(COURSE_POSTS)) if i not in (0, 1)]
            # random.shuffle(post_indices)
            first_done = is_first_rotation_done(chat_id)
            per_post_delay = COURSE_POST_DELAY if not first_done else ROTATION_DELAY
            for i in post_indices:
                await _wait_quiet_since_last_bot_message(chat_id, per_post_delay)
                try:
                    text = COURSE_POSTS[i]
                    reply_markup = kb_course_2()
                    if i == 5:
                        reply_markup = None

                    if i in COURSE_POST_MEDIA or i in COURSE_POST_VIDEOS:
                        media_group = MediaGroupBuilder(caption=text)
                        if i in COURSE_POST_MEDIA:
                            for photo_index in COURSE_POST_MEDIA[i]:
                                media_group.add_photo(media=COURSE_POST_PHOTOS[photo_index])
                        if i in COURSE_POST_VIDEOS:
                            for data in COURSE_POST_VIDEOS[i]:
                                media_group.add_video(
                                    media=FSInputFile(data["path"]),
                                    height=data.get("height"),
                                    width=data.get("width"),
                                )
                        msg = await bot.send_media_group(chat_id, media_group.build())
                        _mark_bot_sent(chat_id)
                        if reply_markup is not None:
                            try:
                                await msg[0].edit_reply_markup(reply_markup=reply_markup)
                            except TelegramBadRequest:
                                await bot.send_message(chat_id, "Мини курс по Р2Р", reply_markup=kb_course())
                                _mark_bot_sent(chat_id)
                    else:
                        await bot.send_message(chat_id, text, parse_mode=ParseMode.HTML, reply_markup=reply_markup)
                        _mark_bot_sent(chat_id)
                except TelegramForbiddenError:
                    SENDING_POSTS.discard(chat_id)
                    return
                except Exception as e:
                    logging.warning("Failed to send course post %d to %s: %s", i + 1, chat_id, e)
            if not first_done:
                set_first_rotation_done(chat_id, True)
    finally:
        SENDING_POSTS.discard(chat_id)

async def access_nurture(user_id: int):
    """Спам до нажатия «ПОЛУЧИТЬ ДОСТУП». Запускать после /start."""
    for i, delay in enumerate(ACCESS_REM_DELAYS):
        await asyncio.sleep(delay)
        if get_stage(user_id) >= 1:
            break
        txt = ACCESS_NUDGE_TEXTS[min(i, len(ACCESS_NUDGE_TEXTS) - 1)]
        try:
            await bot.send_message(user_id, txt, reply_markup=kb_access())
            _mark_bot_sent(user_id)
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
            await bot.send_message(user_id, texts[stage_expected], reply_markup=kb_open(stage_expected),
                                   parse_mode=ParseMode.MARKDOWN)
            _mark_bot_sent(user_id)
        except Exception as e:
            logging.warning("PM reminder failed: %s", e)

# ========= HANDLERS =========

async def start_welcome_sequence(chat_id: int):
    """Sends the full welcome message sequence."""
    set_stage(chat_id, 0)
    set_pm_ok(chat_id, True)
    # Отправляем первый блок с кнопкой
    await send_block(chat_id, BANNER_WELCOME, WELCOME_LONG, reply_markup=kb_access_reply(),
                     parse_mode=ParseMode.MARKDOWN)


@router.message(Command("start"))
async def on_start(m: Message):
    await start_welcome_sequence(m.from_user.id)


@router.message(F.text == "🔑 ПОЛУЧИТЬ ДОСТУП")
async def on_get_access(m: Message):
    uid = m.from_user.id
    stage = get_stage(uid)
    if stage >= 1:
        return
    
    try:
        await m.delete()
    except Exception:
        pass
        
    # Reply to the user's message, removing the ReplyKeyboardMarkup
    sent_message = await m.answer("ДОСТУП ПОЛУЧЕН! 🔓 Уроки доступны.", reply_markup=ReplyKeyboardRemove())
    _mark_bot_sent(m.chat.id)

    # Schedule deletion of the message after 1 second
    asyncio.create_task(delete_message_after_delay(m.chat.id, sent_message.message_id, 1))

    # Отправляем интро к уроку 1 с кнопкой "ОТКРЫТЬ УРОК 1"
    await send_block(uid, BANNER_AFTER4, LESSON1_INTRO, reply_markup=kb_open(1), parse_mode=ParseMode.HTML)

    set_stage(uid, 1)
    asyncio.create_task(remind_if_not_opened(uid, 1, REM1_DELAY))
    asyncio.create_task(access_nurture(uid))
    asyncio.create_task(send_course_posts(uid))









@router.callback_query(F.data == "buy_course")
async def on_buy_course(cb: CallbackQuery):
    await cb.answer("Открываю ссылку на курс...")
    set_loop_stopped(cb.from_user.id, True)
    await cb.message.answer(f"Вот ссылка на курс: {SITE_URL}")
    _mark_bot_sent(cb.message.chat.id)


@router.callback_query(F.data.startswith("open:"))
async def on_open(cb: CallbackQuery):
    await cb.answer()
    try:
        n = int(cb.data.split(":")[1])
    except Exception:
        return

    uid = cb.from_user.id
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass

    if n in (1, 2):
        URLS = {1: LESSON1_URL, 2: LESSON2_URL}
        await send_url_only(cb.message.chat.id, URLS[n])
        _mark_bot_sent(cb.message.chat.id)
        stage = get_stage(uid)
        if n > stage:
            set_stage(uid, n)
        await asyncio.sleep(1)
        asyncio.create_task(auto_send_next_lesson(uid, n))
        return

    if n == 3:
        stage = get_stage(uid)
        if stage < 7:
            await send_block(cb.message.chat.id, BANNER_AFTER2, GATE_BEFORE_L3, reply_markup=kb_subscribe_then_l3(), parse_mode=ParseMode.HTML)
            _mark_bot_sent(cb.message.chat.id)
            if stage < 6:
                set_stage(uid, 6)
        else:
            await send_url_only(cb.message.chat.id, LESSON3_URL)
            _mark_bot_sent(cb.message.chat.id)
            if stage < 8:
                set_stage(uid, 8)
        return


    # Урок 3 → блоки и рассылка постов
    # if n == 3:
    #     # файл уже отправили выше; только блоки/рассылка
    #     async def delayed_blocks(chat_id: int):
    #         await asyncio.sleep(1800)  # Wait 30 minutes after lesson 3
    #         await send_block(chat_id, BANNER_BLOCK6, BLOCK_6, reply_markup=kb_buy_course(), parse_mode=ParseMode.HTML)
    #         await asyncio.sleep(1800)  # Wait 30 minutes before block 7
    #         await send_block(chat_id, BANNER_BLOCK7, BLOCK_7, reply_markup=kb_apply_form(), parse_mode=ParseMode.HTML)
    #
    #     asyncio.create_task(delayed_blocks(cb.message.chat.id))


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
    await cb.answer("Проверяем подписку...", show_alert=False)
    
    uid = cb.from_user.id

    # Делаем небольшую паузу, чтобы дать Telegram время обработать подписку
    await asyncio.sleep(3) 

    if await is_subscribed_telegram(uid):
        # Убираем кнопки после нажатия
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except TelegramBadRequest:
            pass
        # Отправляем файл L3_FOLLOWUP_FILE
        await _send_file_with_fallback(cb.message.chat.id, L3_FOLLOWUP_FILE, None)
        # Отправляем ссылку на 3 урок
        URLS = {1: LESSON1_URL, 2: LESSON2_URL, 3: LESSON3_URL}
        set_stage(uid, 8)
        await send_url_only(cb.message.chat.id, URLS[3])
    else:
        txt = (
            "Пока не вижу твою подписку на дневник.\n"
            "Нажми «Подписаться на дневник», подпишись, и затем снова жми «ПРОВЕРИТЬ»."
        )
        # Не убираем кнопки, если проверка не удалась
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
    # await req.approve()
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
    _mark_bot_sent(m.chat.id)
    try:
        result = await _send_file_with_fallback(m.chat.id, file_or_id, L3_FOLLOWUP_CAPTION or None)
        await m.answer(f"Результат отправки: {result}", parse_mode=None)
        _mark_bot_sent(m.chat.id)
    except Exception as e:
        logging.exception("test_l3 failed: %s", e)
        await m.answer(f"❌ Не вдалося надіслати: {e}", parse_mode=None)
        _mark_bot_sent(m.chat.id)

@router.message(F.forward_from_chat)
async def on_forwarded_from_channel(message: Message):
    ch = message.forward_from_chat
    await message.answer(
        f"Название: {ch.title}\nID: <code>{ch.id}</code>"
    )
    _mark_bot_sent(message.chat.id)

@router.message(Command("diag"))
async def diag(m: Message):
    me = await bot.get_me()
    await m.answer(
        f"*Diag*\nBot: @{me.username}\nDEEP_LINK: {DEEP_LINK}\n"
        f"REM1/2/3={REM1_DELAY}/{REM2_DELAY}/{REM3_DELAY}\n"
        f"NEXT_AFTER_1/2={NEXT_AFTER_1}/{NEXT_AFTER_2}",
        parse_mode=ParseMode.MARKDOWN
    )
    _mark_bot_sent(m.chat.id)

@router.message(Command("stats"))
async def stats(m: Message):
    if ADMIN_ID and m.from_user.id != ADMIN_ID:
        return
    d = _read()
    await m.answer(f"Users tracked: {len(d.get('users', {}))}")
    _mark_bot_sent(m.chat.id)

@router.message(Command("test_error"))
async def test_error(m: Message):
    if ADMIN_ID and m.from_user.id != ADMIN_ID:
        return
    # Test the error notification system
    await send_admin_message("🧪 Test notification: Error notification system is working!")
    await m.answer("Test notification sent to admin.")
    _mark_bot_sent(m.chat.id)

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
        pass
    else:
        pass

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
        await send_admin_message(f"❌ Webhook error: {e}")
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
    except Exception as e:
        logging.error("Failed to delete webhook in polling mode: %s", e)
        await send_admin_message(f"❌ Error deleting webhook in polling mode: {e}")

    logging.info("Starting bot in polling mode...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except Exception as e:
        logging.error("Polling failed: %s", e)
        await send_admin_message(f"❌ Polling error: {e}")
        raise

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
    try:
        me = await bot.get_me()
        DEEP_LINK = f"https://t.me/{me.username}?start=from_channel"
        logging.info("Bot: @%s, Deep-link: %s", me.username, DEEP_LINK)
    except Exception as e:
        logging.error("Failed to get bot info: %s", e)
        await send_admin_message(f"❌ Failed to get bot info: {e}")
        raise

    try:
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
    except Exception as e:
        logging.error("Webhook server failed: %s", e)
        await send_admin_message(f"❌ Webhook server error: {e}")
        raise

if __name__ == "__main__":
    if RUN_MODE.lower() == "polling":
        logging.info("Running in polling mode")
        asyncio.run(run_polling())
    else:
        logging.info("Running in webhook mode")
        asyncio.run(run_webhook())


