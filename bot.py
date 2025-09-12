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
    InlineKeyboardButton, ChatJoinRequest
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramForbiddenError
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

L3_FOLLOWUP_VIDEO = os.getenv("L3_FOLLOWUP_VIDEO", "")
L3_FOLLOWUP_CAPTION = os.getenv("L3_FOLLOWUP_CAPTION", "")
L3_FOLLOWUP_DELAY = int(os.getenv("L3_FOLLOWUP_DELAY", "10"))
L3_FOLLOWUP_FILE_ID = os.getenv("L3_FOLLOWUP_FILE_ID", "").strip().rstrip("\u200b\ufeff\u2060")

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
PENDING_JOIN: dict[int, int] = {}  # user_id -> chat_id (канал), для последующего approve

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

# ========= HELPER FUNCTIONS =========
async def send_block(chat_id: int, banner_url: str, text: str,
                     reply_markup=None, parse_mode=ParseMode.MARKDOWN):
    try:
        if banner_url:
            await bot.send_photo(chat_id, banner_url, caption=text, reply_markup=reply_markup)
        else:
            await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
    except Exception:
        await bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)

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

def _looks_like_videonote(fid: str) -> bool:
    return fid.startswith("DQAC")  # евристика для video_note

async def _send_l3_video_later(chat_id: int, delay: int | None = None):
    """Через delay сек. після відкриття уроку 3 надіслати відео Стаса (якщо задано)."""
    if not L3_FOLLOWUP_FILE_ID:
        return
    await asyncio.sleep(delay if delay is not None else L3_FOLLOWUP_DELAY)
    try:
        if _looks_like_videonote(L3_FOLLOWUP_FILE_ID):
            await bot.send_video_note(chat_id, L3_FOLLOWUP_FILE_ID)
        else:
            await bot.send_video(chat_id, L3_FOLLOWUP_FILE_ID, caption=(L3_FOLLOWUP_CAPTION or None))
    except Exception as e:
        # фолбек: відправити як текст посилання/ід
        txt = (L3_FOLLOWUP_CAPTION + "\n" if L3_FOLLOWUP_CAPTION else "") + L3_FOLLOWUP_FILE_ID
        try:
            await bot.send_message(chat_id, txt, disable_web_page_preview=False, parse_mode=None)
        except Exception as ee:
            logging.warning("L3 followup send failed: %s / %s", e, ee)

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
            await send_block(user_id, BANNER_AFTER2, GATE_BEFORE_L3, reply_markup=kb_subscribe_then_l3())
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
    kb.row(InlineKeyboardButton(text="🔥 Взять мини-курс (999 грн)", url=SITE_URL))
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

WELCOME_LONG = (
    "Привет✌️\n\n"
    "У меня для тебя подарок, сразу 3 бесплатных урока по P2P 🤝\n\n"
    "Я Стас Грибовский, эксперт в сфере Р2Р уже более 3 лет!\n"
    "Тут тебя ждет интенсив по Р2Р арбитражу 🚀\n\n"
    "Наша цель — понять основу Р2Р и выйти на свой первый доход в этой сфере!\n"
    "Я собрал для тебя практику и реальные кейсы: шаг за шагом покажу, как работает P2P и доведу тебя до первого результата!\n\n"
    "👉В последнем уроке тебя ждет связка, применив которую ты выйдешь на свой первый доход в Р2Р.\n\n"
    "Поэтому, выдели время, налей чашечку чая, устройся поудобнее и начинаем!\n\n"
    "✅ В интенсиве тебя ждут 3 бесплатных  урока:\n"
    "1️⃣ Что такое P2P в 2025 году и почему это возможность, которую нельзя пропустить.\n"
    "2️⃣ Как я заработал $50 000 и новый Mercedes за 3 месяца\n"
    "3️⃣ Связка на Р2Р: 60$ за два часа"
)

LESSON1_INTRO = (
    "Сейчас перед тобой будет первый урок по P2P-арбитражу, который я подготовил именно для тебя.\n\n"
    "В нём ты узнаешь:\n"
    "• что такое P2P и как это работает;\n"
    "• как P2P существовало ещё тысячи лет назад и почему это вечная профессия;\n"
    "• что нужно, чтобы начать зарабатывать на P2P.\n\n"
    "А ещё я подготовил для тебя крутой бонус 🎁 — ты получишь его после просмотра всех трёх уроков.\n"
    "Поэтому не откладывай на потом и приступай к просмотру прямо сейчас!\n\n"
    "Готов начинать?"
)

AFTER_L1 = (
    "Ты большой молодец, что посмотрел первый урок! 🙌\n\n"
    "Я вложил в него много усилий и надеюсь, что он был для тебя полезен. "
    "Буду рад, если ты напишешь мне отзыв в Instagram и поделишься своими впечатлениями после просмотра.\n\n"
    "А теперь не будем тянуть — держи доступ ко второму уроку 🚀\n"
    "Напоминаю: в третьем уроке я раскрою схему, которую ты сможешь внедрить в свою работу и зарабатывать от 800$ в месяц!\n\n"
    "Нажимай на кнопку ниже и приступай к просмотру 👀"
)

AFTER_L2 = (
    "Большая часть нашего интенсива уже позади 🔥\n\n"
    "Сейчас тебя ждёт третий, заключительный урок, в котором я покажу схему, на которой на твоих глазах "
    "сделаю +2% к начальному депозиту всего за несколько минут. И да — позже ты сможешь просто повторять за мной те же самые шаги!\n\n"
    "Не откладывай на потом — изучи эту связку прямо сейчас"
)

GATE_BEFORE_L3 = (
    "Так же, по секрету, хочу с тобой поделиться: я веду дневник, в котором пишу пост каждый вечер. \n"
    "Там я делюсь полезными инсайтами, бизнес-советами, своими мыслями и даю ценные рекомендации.\n\n"
    "Некоторое время назад я поставил себе цель — купить новый Mercedes AMG с нуля всего за 180 дней 🔥\n"
    "Я не знаю, получится ли у меня, но ты можешь стать частью этого.\n\n"
    "Также ты можешь легко заработать: если заметишь, что я не выложил пост в какой-то из дней — напиши мне об этом лично, и я скину тебе 50$.\n\n"
    "Чтобы получить третий урок, в котором я раскрою все секреты связки, на которой заработал и продолжаю зарабатывать до сих пор, подпишись на мой дневник 👇"
)

BLOCK_6 = (
    "Хочешь освоить P2P и начать зарабатывать от $100 в день?\n\n"
    "Я представляю тебе мини-курс, в котором:\n"
    "— 5 уроков по 30 минут\n"
    "— рабочая связка которая приносит от 100$ ежедневно. Твоя задача повторять ее за мной и внедрить в свою жизнь \n"
    "— пошаговые инструкции и готовые шаблоны\n"
    "— бонус — промокод на $100 для следующих потоков\n\n"
    "Кол-во мест ограничено⛔️\n\n"
    "Цена 999 грн"
)

BLOCK_7 = (
    "Как ты уже понял, у меня есть личное обучение по P2P, которое прошли сотни людей. "
    "Уникальность программы в том, что все кураторы — это бывшие ученики, а студенты выходят на доход от 1500$ уже в первый месяц после старта.\n\n"
    "Что делает обучение особенным:\n"
    "• Работа в самой безопасной нише в крипте, где ученики зарабатывают до 10% в день.\n"
    "• Более 3 лет моего опыта в сфере, которым я делюсь через самые актуальные знания.\n"
    "• Десятки разных схем и связок по арбитражу: P2P, фандинг, межбиржевой, spot/futures, CEX/DEX. Каждый найдёт то, что подойдёт именно ему.\n"
    "• Уникальное комьюнити, где есть как специалисты из разных областей, так и владельцы крупных компаний.\n\n"
    "И это только часть того, что ждёт внутри — многое остаётся под завесой 😉\n\n"
    "Чтобы попасть в следующий поток, заполняй гугл-форму ниже или связывайся со мной @"
)

# ========= ДОСТУП/НАПОМИНАНИЯ =========
ACCESS_NUDGE_TEXTS = [
    "Вижу, ты ещё не забрал доступ к урокам. Нажми ниже — начнём с первого 👇",
    "Напомню про интенсив: 3 бесплатных урока ждут тебя. Забери доступ 👇",
    "Давай не откладывать — забирай доступ и стартуем прямо сейчас 👇",
]

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

@router.message(Command("start"))
async def on_start(m: Message):
    set_stage(m.from_user.id, 0)
    # Отправляем первый блок без кнопки
    await send_block(m.chat.id, BANNER_WELCOME, WELCOME_LONG)
    # Отправляем новый блок с описанием урока и кнопкой
    await send_block(m.chat.id, BANNER_AFTER4, LESSON1_INTRO, reply_markup=kb_access())

async def _approve_later(chat_id: int, user_id: int):
    try:
        await bot.approve_chat_join_request(chat_id, user_id)
    except Exception as e:
        logging.warning("Approve later failed: %s", e)

@router.callback_query(F.data.startswith("open:"))
async def on_open(cb: CallbackQuery):
    await cb.answer()
    # Убираем кнопки после нажатия
    await cb.message.edit_reply_markup(reply_markup=None)
    
    try:
        n = int(cb.data.split(":")[1])
    except Exception:
        return

    uid = cb.from_user.id

    # Убираем проверки просмотра - уроки доступны по порядку автоматически

    # 2) Гейт на подписку перед Уроком 3 (только если настроен телеграм-канал дневника)
    if n == 3 and DIARY_TG_CHAT_ID:
        if not has_diary_request(uid):
            await send_block(cb.message.chat.id, BANNER_AFTER5, GATE_BEFORE_L3, reply_markup=kb_subscribe_then_l3())
            return

    # 3) Отдаём ТОЛЬКО ссылку без кнопок
    URLS = {1: LESSON1_URL, 2: LESSON2_URL, 3: LESSON3_URL}
    await send_url_only(
        cb.message.chat.id,
        URLS[n],
        reply_markup=None
    )

    # 4) Обновляем стадию
    stage = get_stage(uid)
    if n > stage:
        set_stage(uid, n)

       # 5) Для урока 3 сразу финальные блоки (после ссылки)
    if n == 3:
           # Сначала отправляем видео Стаса
        try:
            if _looks_like_videonote(L3_FOLLOWUP_FILE_ID):
                await bot.send_video_note(cb.message.chat.id, L3_FOLLOWUP_FILE_ID)
            else:
                await bot.send_video(
                    cb.message.chat.id,
                    L3_FOLLOWUP_FILE_ID,
                    caption=(L3_FOLLOWUP_CAPTION or None)
                )
        except Exception as e:
            txt = (L3_FOLLOWUP_CAPTION + "\n" if L3_FOLLOWUP_CAPTION else "") + L3_FOLLOWUP_FILE_ID
            await bot.send_message(cb.message.chat.id, txt, disable_web_page_preview=False, parse_mode=None)

        # Через 1 минуту кидаем BLOCK_6 и BLOCK_7
        async def delayed_blocks(chat_id: int):
            try:
                await asyncio.sleep(60)
                await send_block(chat_id, BANNER_BLOCK6, BLOCK_6, reply_markup=kb_buy_course())
                await asyncio.sleep(60)
                await send_block(chat_id, BANNER_BLOCK7, BLOCK_7, reply_markup=kb_apply_form())
            except Exception as e:
                logging.warning("Delayed blocks failed: %s", e)

        asyncio.create_task(delayed_blocks(cb.message.chat.id))

        # === Рассылка 8 постов по 1 каждые 5 часов ===
        def kb_course() -> InlineKeyboardMarkup:
            kb = InlineKeyboardBuilder()
            kb.row(InlineKeyboardButton(text="🔥 Мини курс Р2Р", url=SITE_URL))
            return kb.as_markup()

        async def send_course_posts(chat_id: int):
            for i, text in enumerate(COURSE_POSTS, start=1):
                try:
                    await bot.send_message(chat_id, text, reply_markup=kb_course())
                except Exception as e:
                    logging.warning("Failed to send course post %s: %s", i, e)
                if i < len(COURSE_POSTS):
                    await asyncio.sleep(5 * 60 * 60)  # 5 часов

        asyncio.create_task(send_course_posts(cb.message.chat.id))
       
        COURSE_POSTS = [
    # Пост 1
    """Многие новички которые только заходят в сферу Р2Р думают, что нужно обладать каким-то особым навыком или везением. 
На самом деле — нет. Всё, что требуется — это желание разобраться и готовность действовать.

У многих есть страхи. Страхи что не выйдет, что не получится, что обманут и т.д. 
И бороться с этими всеми страхами можно только лишь с подходом к Р2Р с правильной стороны и с хорошим наставником.  

Именно поэтому я создал свой курс: чтобы дать людям не пустые обещания, а пошаговую систему, которая работает у меня и у моих учеников.  

На фото выше — отзывы тех, кто пришёл ко мне на обучение.  
Кто-то делал первые 30-50$ в день.  
Кто-то закрывал неделю с профитом в $300–400.  
А те, кто давно начинали уже имеют свои команды и доходы в стабильных несколько тысяч $ каждый месяц.  

Вся суть Р2Р это начать с малого, просто чтобы понять и попробовать.  
А со временем у тебя в руках оказывается инструмент финансовой свободы.  

Здесь нет потолка, нет ограничений — всё зависит только от того, сколько ты готов вкладывать усилий.  

И да, именно поэтому я считаю P2P профессией будущего. Люди всегда будут обменивать: вчера это было золото на серебро, сегодня крипта на фиат, завтра — ещё что-то новое.  

Но суть одна: спрос есть и будет всегда.  

А теперь вопрос к тебе: ты с нами или будешь дальше наблюдать за результатами других и потом жалеть, что не зашёл вовремя?""",

    # Пост 2
    """Сейчас Р2Р для меня — это профессия и основной доход.  
Но когда я только заходил в эту сферу, я ошибочно считал это «темкой» на несколько месяцев.  

Реальность оказалась куда другой. Со временем я понял, что Р2Р — это далеко не темка, а прогнозируемый бизнес на дистанции, который даёт хорошие результаты.  

И результат не заставил себя ждать: через какое-то время работы я купил себе Mercedes.  

P2P дало мне свободу. И не ту лживую, как какие-то «темки» или профессии, а настоящую.  
Где нет начальника, привязанности к месту и потолка дохода.  

Благодаря Р2Р я могу не переживать о завтрашнем дне и, что не менее важно, провести его как в Польше, так и в Испании.  

Здесь я научился ценить эту свободу.  
Свободу выбора, а не обязанность работать на кого-то.  
Не ту, о которой любят красиво говорить, а настоящую — когда ты не зависишь от зарплаты в конце месяца, не смотришь на начальника, не переживаешь, что завтра тебя могут уволить.  

P2P дало мне уверенность, что у меня всегда будет доход.  
Потому что люди всегда будут обменивать деньги.  
Раньше это могли быть золотые и серебряные монеты, сейчас же — криптовалюта и деньги.  

И вот в этом для меня смысл: я нашёл своё дело, которое не привязано ни к стране, ни к работодателю.  
У меня есть ноутбук, телефон и рынок, который работает 24/7.  

Кто-то всю жизнь ищет «свою профессию». А я могу сказать честно: я её нашёл.  
Для меня P2P — это профессия будущего, которая уже сегодня даёт то, к чему многие идут годами: стабильный доход, свободу и независимость.""",

    # Пост 3
    """Я, конечно, удивлён, почему ты не хочешь получить БЕСПЛАТНО схему, на которой мои ученики зарабатывают в среднем 2500$ в месяц 🤔  

Ладно, как исключение, даю только тебе доступ к этому уроку, где я раскрыл всю схему.  

Забирай по кнопке ниже — урок скоро исчезнет, и ты можешь остаться без доступа 👇""",

    # Пост 4
    """Я понимаю, что ты очень занят и у тебя много дел, но поверь: после просмотра этого урока ты поймёшь основы P2P и откроешь для себя новую сферу заработка ⏳  

Забирай готовый урок по кнопке ниже (доступ ограничен) 👇""",

    # Пост 5
    """Хороший пример преимущества Р2Р над другими сферами — это полная независимость.  

Независимость от всего:  

• Время:  
Не хочешь или не можешь работать днём — работаешь ночью.  

• Место:  
Не хочешь работать из своего города или страны? Р2Р — это онлайн, работай там, где тебе удобно.  

• Люди:  
Не хочешь начальника? Его не будет. Хочешь команду? Собираешь и управляешь.  

• Умения:  
Боишься, что не разберёшься?  
Ко мне на обучение приходят люди, у которых нет даже минимального понятия не то что в Р2Р, а в крипте в целом.  
После месяца обучения их доход вырастает до 1000$+.  

На видео сверху хороший пример. Один из учеников решил сделать себе мини-отпуск и поехать на отдых за счёт Р2Р. Итог — за отдых он заработал больше, чем потратил.  

Р2Р — это инструмент, который в правильных руках даёт полную свободу и независимость.  
Вопрос, готов ли ты это взять?""",

    # Пост 6
    """А это пример одного из первых учеников, Богдана.  

Богдан до Р2Р работал на заводе в Польше и хотел жениться. По его словам, работа на заводе ему надоела, и он решил, что нужно что-то в жизни менять.  

Что сделал Богдан?  
Он пошёл на моё обучение по Р2Р. Несмотря на то, что он раньше не работал в Р2Р и ему было трудно поначалу, через два месяца Богдан вышел на 2500$+ ежемесячно.  

Хотя у него не было ни больших денег для оборота, ни знаний в Р2Р.  
У него было лишь желание — желание научиться и желание заработать денег.  

И он смог. Сейчас он может себе позволить и свадьбу на Мадейре, и хорошую жизнь без работы на кого-то.  

Если получилось у него — получится и у тебя.""",

    # Пост 7
    """Итак, почему же именно Р2Р, а не другие ниши? 👀  

1) Нам не нужно никуда вкладывать деньги и что-то покупать, как в товарном бизнесе. В Р2Р мы наши деньги никуда не деваем — они всегда у нас перед глазами.  

2) Р2Р — это бизнес онлайн. Нету привязки ко времени (многие работают в ночное время), к месту и к людям.  

3) В Р2Р нет потолка по заработку. Здесь можно масштабироваться и строить свои команды.  

4) Не нужно иметь много денег для старта. Достаточно начинать с 300$.  

5) Лёгкий старт для новичков. Здесь не нужно учиться годами (в отличие от фьючерсной торговли).  

6) Р2Р — сфера без рисков, в отличие от других направлений, связанных с криптовалютой.  

Самое важное, что нужно понять новичку: Р2Р — это не «темка», а полноценный бизнес, в который нужно вкладывать силы и время.  

Я могу дать тебе все необходимые знания, чтобы ты начал развиваться в этой сфере.  
Вопрос: готов ли ты их взять?""",

    # Пост 8
    """Давай разберём, в чём уникальность этого мини-курса и почему его стоит приобрести.  

Во-первых — это цена. Где ещё ты видел обучение по P2P дешевле 1000 грн?  
Во-вторых — внутри 5 полноценных уроков по 30 минут каждый.  
В-третьих — в одном из уроков показана в деталях рабочая связка, на которой я и мои ученики зарабатывают от 100$ ежедневно.  

Также в курсе ты получишь:  
• пошаговый план, как выйти на стабильный доход уже в первый месяц;  
• разбор частых ошибок новичков, чтобы ты их не допустил;  
• готовые шаблоны и инструкции для быстрого старта.  

Кроме того, я показал, как построить свою команду, масштабировать процессы и грамотно управлять ими.  

Тебя ждёт активная неделя обучения, после которой твоя жизнь разделится на «до» и «после».  
Ты сможешь работать из дома и зарабатывать не меньше, чем твой прошлый начальник.  

А ещё в курсе тебя ждёт подарок 🎁  
Не скажу, в каком уроке — будь внимателен 😉  

Мой подарок — это промокод на 100$ для участия в следующих потоках обучения.  
Когда захочешь присоединиться, просто скажешь кодовое слово с урока и активируешь скидку.  
Таким образом, ты выйдешь в плюс на 80$ (поскольку цена мини-курса 20$, а скидка 100$).  

Занято 63/100 мест.  

А сейчас я даю тебе ссылку на мини-курс, который подготовил специально для тебя 👇"""
    ]

# Обработчик "done:" убран - теперь автоматическая отправка через 30 минут

@router.callback_query(F.data == "check_diary")
async def check_diary(cb: CallbackQuery):
    await cb.answer()
    # Убираем кнопки после нажатия
    await cb.message.edit_reply_markup(reply_markup=None)
    
    uid = cb.from_user.id

    if DIARY_TG_CHAT_ID and has_diary_request(uid):
        URLS = {1: LESSON1_URL, 2: LESSON2_URL, 3: LESSON3_URL}
        await send_url_only(cb.message.chat.id, URLS[3])
        await cb.message.answer("Поздравляю! 🎉 Ты получил доступ к третьему уроку.")
        await send_block(cb.message.chat.id, BANNER_BLOCK6, BLOCK_6, reply_markup=kb_buy_course())
        await send_block(cb.message.chat.id, BANNER_BLOCK7, BLOCK_7, reply_markup=kb_apply_form())
        asyncio.create_task(_send_l3_video_later(cb.message.chat.id))
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
        set_diary_request(uid, True)
        logging.info("Diary join-request captured for uid=%s", uid)
        return

    PENDING_JOIN[uid] = req.chat.id
    set_stage(uid, 0)

    try:
        await send_block(uid, BANNER_WELCOME, WELCOME_LONG, reply_markup=kb_access())
        set_pm_ok(uid, True)
        asyncio.create_task(access_nurture(uid))
    except TelegramForbiddenError:
        set_pm_ok(uid, False)
    except Exception as e:
        logging.warning("PM send failed: %s", e)

@router.message(Command("test_l3"))
async def test_l3(m: Message):
    fid = L3_FOLLOWUP_FILE_ID
    if not fid:
        return await m.answer("L3_FOLLOWUP_FILE_ID порожній у .env", parse_mode=None)
    try:
        if _looks_like_videonote(fid):
            await bot.send_video_note(m.chat.id, fid)
            return await m.answer("✅ Надіслано як video note", parse_mode=None)
        else:
            await bot.send_video(m.chat.id, fid, caption=(L3_FOLLOWUP_CAPTION or None))
            return await m.answer("✅ Надіслано як звичайне відео", parse_mode=None)
    except Exception as e:
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
        await asyncio.Future()  # run forever
    except KeyboardInterrupt:
        pass
    finally:
        await runner.cleanup()

if __name__ == "__main__":
    if RUN_MODE.lower() == "polling":
        logging.info("Running in polling mode")
        asyncio.run(run_polling())
    else:
        asyncio.run(run_webhook())







