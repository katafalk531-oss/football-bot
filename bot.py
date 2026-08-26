import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiohttp import web, ClientSession

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "7575444568:AAEHYZMjzWvlUHYbB6-ZkDv8e42xpgpV9YA"
RAPIDAPI_KEY = "0cf379b94fmsh2e9e4e5fbdc2b78p1efe49jsnb7dc15ae2f06"
# =============================================
# ================= xG МОДУЛЬ =================
from aiohttp import ClientSession

# Заглушка (ты её заменишь на настоящую функцию)
XG_API = f"https://v3.football.api-sports.io/fixtures/statistics"
XG_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "v3.football.api-sports.io"
}
logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ПОИСК КОМАНДЫ ---
async def search_team(session, team_name):
    url = "https://v3.football.api-sports.io/teams"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "v3.football.api-sports.io"
    }
    params = {"name": team_name, "search": team_name}
    async with session.get(url, headers=headers, params=params) as resp:
        data = await resp.json()
        if data.get("response"):
            return data["response"][0]["team"]
    return None

# --- ПОСЛЕДНИЕ 5 МАТЧЕЙ + xG ---
async def get_team_form_xg(session, team_id):
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "v3.football.api-sports.io"
    }
    params = {"team": team_id, "last": 5, "status": "FT"}
    async with session.get(url, headers=headers, params=params) as resp:
        data = await resp.json()
    
    form = []
    xg_home = xg_away = 0.0
    for fixture in data.get("response", []):
        teams = fixture["teams"]
        if teams["home"]["id"] == team_id:
            form.append("W" if fixture["goals"]["home"] > fixture["goals"]["away"] else 
                        "L" if fixture["goals"]["home"] < fixture["goals"]["away"] else "D")
            xg_home += fixture.get("teams", {}).get("home", {}).get("statistics", {}).get("xG", {}).get("home", 0) or 0
        else:
            form.append("W" if fixture["goals"]["away"] > fixture["goals"]["home"] else 
                        "L" if fixture["goals"]["away"] < fixture["goals"]["home"] else "D")
            xg_away += fixture.get("teams", {}).get("away", {}).get("statistics", {}).get("xG", {}).get("away", 0) or 0
    
    score1 = sum(3 if x == "W" else 1 if x == "D" else 0 for x in form)
    score2 = sum(3 if x == "W" else 1 if x == "D" else 0 for x in form[1:])  # простая средняя форма
    
    avg_xg = (xg_home + xg_away) / 2
    return form, score1, score2, round(avg_xg, 2)

# --- H2H ---
async def get_match_xg(session, fixture_id):
    """Получаем xG для одного матча (точные данные API)"""
    async with session.get(XG_API, headers=XG_HEADERS, params={"fixture": fixture_id}) as resp:
        data = await resp.json()
    if not data.get("response"):
        return 0.0, 0.0, 0.0
    stats = data["response"][0]
    home_xg = stats.get("teams", {}).get("home", {}).get("statistics", {}).get("xG", {}).get("home", 0) or 0
    away_xg = stats.get("teams", {}).get("away", {}).get("statistics", {}).get("xG", {}).get("away", 0) or 0
    return round(home_xg, 2), round(away_xg, 2), round(home_xg - away_xg, 1)

async def get_h2h(session, team1_id, team2_id):
    url = "https://v3.football.api-sports.io/fixtures/headtohead"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "v3.football.api-sports.io"
    }
    params = {"h2h": f"{team1_id}-{team2_id}", "last": 5}
    async with session.get(url, headers=headers, params=params) as resp:
        data = await resp.json()
    
    wins1 = wins2 = draws = 0
    for fixture in data.get("response", []):
        if fixture["teams"]["home"]["id"] == team1_id:
            if fixture["goals"]["home"] > fixture["goals"]["away"]:
                wins1 += 1
            elif fixture["goals"]["home"] < fixture["goals"]["away"]:
                wins2 += 1
            else:
                draws += 1
        else:
            if fixture["goals"]["away"] > fixture["goals"]["home"]:
                wins1 += 1
            elif fixture["goals"]["away"] < fixture["goals"]["home"]:
                wins2 += 1
            else:
                draws += 1
    return wins1, draws, wins2

# --- xG для матча (теперь в основном анализе) ---
async def get_match_xg(session, fixture_id):
    url = "https://v3.football.api-sports.io/fixtures/statistics"
    headers = {
        "X-RapidAPI-Key": RAPIDAPI_KEY,
        "X-RapidAPI-Host": "v3.football.api-sports.io"
    }
    params = {"fixture": fixture_id}
    async with session.get(url, headers=headers, params=params) as resp:
        data = await resp.json()
    if not data.get("response"):
        return 0.0, 0.0
    stats = data["response"][0]
    home_xg = stats.get("teams", {}).get("home", {}).get("statistics", {}).get("xG", {}).get("home", 0) or 0
    away_xg = stats.get("teams", {}).get("away", {}).get("statistics", {}).get("xG", {}).get("away", 0) or 0
    return round(home_xg, 2), round(away_xg, 2)

# --- АНАЛИЗ МАТЧА (с xG) ---
async def analyze_match(team1_name, team2_name):
    async with ClientSession() as session:
        team1 = await search_team(session, team1_name)
        team2 = await search_team(session, team2_name)
        
        if not team1 or not team2:
            return None, "Команды не найдены. Пиши на английском."

        # === Форма + xG ===
        form1, score1, _, xg1 = await get_team_form_xg(session, team1["id"])
        form2, score2, _, xg2 = await get_team_form_xg(session, team2["id"])
        h2h_w1, h2h_d, h2h_w2 = await get_h2h(session, team1["id"], team2["id"])

        # === Простой расчёт уверенности ===
        total = score1 + score2 + (h2h_w1 * 2) + (h2h_w2 * 2) + (h2h_d * 1)
        if total == 0:
            prediction = "Ничья"
            conf = 33
        else:
            prob1 = (score1 + h2h_w1 * 2) / total * 100
            prob2 = (score2 + h2h_w2 * 2) / total * 100
            if prob1 > prob2 + 15:
                prediction = f"Победа {team1_name}"
                conf = int(prob1)
            elif prob2 > prob1 + 15:
                prediction = f"Победа {team2_name}"
                conf = int(prob2)
            else:
                prediction = "Ничья или близкий матч"
                conf = 40

        # === xG для матча (если есть fixture_id — добавь сюда) ===
        fixture_id = None  # сюда подставь реальный ID матча, если хочешь точный xG
        xG1, xG2, xg_diff = 0.0, 0.0, 0.0
        if fixture_id:
            xG1, xG2, xg_diff = await get_match_xg(session, fixture_id)

        return {
            "team1": team1["name"],
            "team2": team2["name"],
            "form1": "".join(form1) if form1 else "N/A",
            "form2": "".join(form2) if form2 else "N/A",
            "h2h": f"{h2h_w1} - {h2h_d} - {h2h_w2}",
            "prediction": prediction,
            "confidence": conf,
            "xG1": xG1,
            "xG2": xG2,
            "xg_diff": xg_diff
        }, None
        
        return {
            "team1": team1["name"],
            "team2": team2["name"],
            "form1": "".join(form1) if form1 else "N/A",
            "form2": "".join(form2) if form2 else "N/A",
            "h2h": f"{h2h_w1} - {h2h_d} - {h2h_w2}",
            "prediction": prediction,
            "confidence": conf,
            "xG1": xg1,
            "xG2": xg2
        }, None

# --- ОБРАБОТЧИКИ ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Я бот для анализа футбольных матчей с xG.\n\n/predict Спартак Зенит\n/help")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("🆘 /predict Команда1 Команда2\n\nНазвания лучше на английском.\nТеперь с xG, формой и H2H!")

@dp.message(Command("predict"))
async def cmd_predict(message: types.Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❗ Пример: /predict Spartak Zenit")
        return
    
    team1, team2 = args[1], args[2]
    await message.answer(f"🔍 Анализирую {team1} vs {team2} с xG...")

 result, error = await analyze_match(team1, team2)
    if error:
        await message.answer(error)
        return

    xG1 = result["xG1"]
    xG2 = result["xG2"]
    xg_diff = result["xg_diff"]

    answer = (
        f"📊 *Анализ: {result['team1']} — {result['team2']}*\n\n"
        f"🔥 Форма {result['team1']}: {result['form1']}\n"
        f"🔥 Форма {result['team2']}: {result['form2']}\n"
        f"🤝 H2H: {result['h2h']}\n\n"
        f"🧠 *Прогноз:* {result['prediction']}\n"
        f"📈 Уверенность: {result['confidence']}%\n\n"
        f"⚽ xG: {result['team1']} {xG1} — {result['team2']} {xG2} (разница {xg_diff:+.1f})\n\n"
        f"⚠️ _Прогноз на основе статистики. Играйте ответственно._"
    )
    await message.answer(answer, parse_mode="Markdown")

@dp.message(F.text)
async def echo_handler(message: types.Message):
    await message.answer("Напиши /help для списка команд")

# Веб-сервер (оставляем как было)
async def handle_ping(request):
    return web.Response(text="Bot is alive!")

async def start_web_server():
    app = web.Application()
    app.router.add_get('/', handle_ping)
    port = int(os.getenv("PORT", 8080))
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info(f"Web server started on port {port}")

async def main():
    await asyncio.gather(start_web_server(), dp.start_polling(bot))

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Бот остановлен")
