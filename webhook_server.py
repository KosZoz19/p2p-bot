# webhook_server.py
import os
import asyncio
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import Update

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "supersecret")  # любой токен
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL")  # например, https://your-service.onrender.com
PORT = int(os.getenv("PORT", "10000"))

bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN))
dp = Dispatcher()

# импортируй сюда твои хендлеры
import bot   # <-- твой bot.py (без main() и asyncio.run)
dp.include_router(bot.dp)  # подключаем все обработчики из bot.py

async def on_startup(app: web.Application):
    await bot.delete_webhook(drop_pending_updates=True)
    await bot.set_webhook(
        url=f"{RENDER_EXTERNAL_URL}/webhook/{WEBHOOK_SECRET}",
        secret_token=WEBHOOK_SECRET,
    )

async def on_shutdown(app: web.Application):
    await bot.session.close()

async def handle_webhook(request: web.Request):
    if request.match_info.get("token") != WEBHOOK_SECRET:
        return web.Response(status=403)
    data = await request.json()
    update = Update.model_validate(data)
    await dp.feed_update(bot, update)
    return web.Response(text="OK")

app = web.Application()
app.router.add_post(f"/webhook/{{token}}", handle_webhook)
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)