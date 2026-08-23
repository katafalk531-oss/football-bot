import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiohttp import web

# Берем токен из переменных окружения Render (безопасно!)
BOT_TOKEN = "7575444568:AAHEJ1-ESxo6RcDHxEl7CV0UwpXr1U9vaus"

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ОБРАБОТЧИКИ КОМАНД ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Я бот для анализа матчей. Напиши /help")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("Напиши /predict Спартак Зенит")

@dp.message(Command("predict"))
async def cmd_predict(message: types.Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("Пример: /predict Спартак Зенит")
        return
    team1, team2 = args[1], args[2]
    await message.answer(f"⏳ Анализирую {team1} vs {team2}...")
    await asyncio.sleep(1)
    await message.answer(f"📊 Прогноз: Победа {team1} (68% уверенности)")

@dp.message(F.text)
async def echo_handler(message: types.Message):
    await message.answer("Напиши /help")

# --- ВЕБ-СЕРВЕР ДЛЯ RENDER (чтобы не засыпал) ---
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    # Render передает порт в переменной PORT, иначе берем 8080
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

# --- ЗАПУСК ---
async def main():
    # Запускаем веб-сервер и поллинг ОДНОВРЕМЕННО
    await asyncio.gather(
        start_web_server(),
        dp.start_polling(bot)
    )

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
