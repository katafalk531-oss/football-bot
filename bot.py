import asyncio
import logging
import os
import time
import json
from collections import defaultdict
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiohttp import web, ClientSession

# ================= НАСТРОЙКИ =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
RAPIDAPI_KEY = os.getenv("RAPIDAPI_KEY")
# =============================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= УВЕЛИЧЕННОЕ КЭШИРОВАНИЕ (24 часа) =================
CACHE = {"teams": {}, "fixtures": {}, "h2h": {}}
CACHE_TTL = 86400
last_call_time = 0
MIN_INTERVAL = 1.0
ERROR_LIMIT = 429

# ================= ФУНКЦИИ =================
async def safe_call(session, url, headers, params=None):
    global last_call_time
    now = time.time()
    if now - last_call_time < MIN_INTERVAL:
        await asyncio.sleep(MIN_INTERVAL - (now - last_call_time))
    last_call_time = time.time()
    
    async with session.get(url, headers=headers, params=params) as resp:
        data = await resp.json()
        if resp.status == ERROR_LIMIT:
            logging.warning("Лимит запросов исчерпан.")
            return {"error": "СЕРВИС_ЗАБЛОКИРОВАН"}
        return data

async def search_team(session, team_name):
    if team_name in CACHE["teams"]:
        return CACHE["teams"][team_name]
    url = "https://v3.football.api-sports.io/teams"
    headers = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "v3.football.api-sports.io"}
    params = {"name": team_name, "search": team_name}
    data = await safe_call(session, url, headers, params)
    if isinstance(data, dict) and "error" in data:
        return None
    if data.get("response"):
        team = data["response"][0]["team"]
        CACHE["teams"][team_name] = team
        return team
    return None

async def get_team_form_xg(session, team_id, team_name=None):
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "v3.football.api-sports.io"}
    params = {"team": team_id, "last": 5, "status": "FT"}
    data = await safe_call(session, url, headers, params)
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
    avg_xg = (xg_home + xg_away) / 2 if (xg_home + xg_away) > 0 else 0.0
    return form, score1, round(avg_xg, 2)

async def get_h2h(session, team1_id, team2_id):
    key = f"{team1_id}-{team2_id}"
    if key in CACHE["h2h"]:
        return CACHE["h2h"][key]
    url = "https://v3.football.api-sports.io/fixtures/headtohead"
    headers = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "v3.football.api-sports.io"}
    params = {"h2h": key, "last": 5}
    data = await safe_call(session, url, headers, params)
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
    CACHE["h2h"][key] = (wins1, draws, wins2)
    return wins1, draws, wins2

async def get_h2h_xg(session, team1_id, team2_id):
    return 0.0, 0.0, 0.0

async def get_match_xg(session, fixture_id):
    url = "https://v3.football.api-sports.io/fixtures/statistics"
    headers = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "v3.football.api-sports.io"}
    params = {"fixture": fixture_id}
    data = await safe_call(session, url, headers, params)
    if isinstance(data, dict) and "error" in data:
        return 0.0, 0.0, 0.0
    if not data.get("response"):
        return 0.0, 0.0, 0.0
    stats = data["response"][0]
    home_xg = stats.get("teams", {}).get("home", {}).get("statistics", {}).get("xG", {}).get("home", 0) or 0
    away_xg = stats.get("teams", {}).get("away", {}).get("statistics", {}).get("xG", {}).get("away", 0) or 0
    return round(home_xg, 2), round(away_xg, 2), round(home_xg - away_xg, 1)

async def get_today_matches(session):
    today = datetime.now().strftime("%Y-%m-%d")
    params = {"date": today, "status": "NS"}
    url = "https://v3.football.api-sports.io/fixtures"
    headers = {"X-RapidAPI-Key": RAPIDAPI_KEY, "X-RapidAPI-Host": "v3.football.api-sports.io"}
    data = await safe_call(session, url, headers, params)
    return data.get("response", [])[:20]

async def analyze_match(team1_name, team2_name):
    async with ClientSession() as session:
        team1 = await search_team(session, team1_name)
        team2 = await search_team(session, team2_name)
        
        if not team1 or not team2:
            return None, "Команды не найдены."

        form1, score1, xg1 = await get_team_form_xg(session, team1["id"], team1_name)
        form2, score2, xg2 = await get_team_form_xg(session, team2["id"], team2_name)
        h2h_w1, h2h_d, h2h_w2 = await get_h2h(session, team1["id"], team2["id"])
        
        fixture_id = None
        xG1, xG2, xg_diff = await get_match_xg(session, fixture_id) if fixture_id else (xg1, xg2, 0.0)
        
        avg_xg = (xG1 + xG2) / 2
        value = (xG1 - xG2) / avg_xg if avg_xg > 0 else 0
        
        h2g1, h2g2, h2g_diff = await get_h2h_xg(session, team1["id"], team2["id"])
        
        total = score1 + score2 + (h2h_w1 * 2) + (h2h_w2 * 2) + (h2h_d * 1) + int(abs(value) * 10) + int(abs(h2g_diff) * 8)
        prob1 = (score1 + h2h_w1 * 2) / total * 100
        if prob1 > 50:
            prediction = f"Победа {team1_name}"
            conf = int(prob1)
        else:
            prediction = "Ничья или близкий матч"
            conf = 40

        return {
            "team1": team1["name"],
            "team2": team2["name"],
            "form1": "".join(form1) if form1 else "N/A",
            "form2": "".join(form2) if form2 else "N/A",
            "h2h": f"{h2h_w1} - {h2h_d} - {h2h_w2}",
            "xG1": xG1,
            "xG2": xG2,
            "xg_diff": xg_diff,
            "value": round(value, 2),
            "h2g_diff": h2g_diff,
            "prediction": prediction,
            "confidence": conf
        }, None

# ================= ОБРАБОТЧИК =================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer("👋 Привет! Я твой xG-бот для анализа футбольных матчей.\n\n"
                         "Команды:\n"
                         "/predict Команда1 Команда2 — анализ матча с xG\n"
                         "/today — матчи сегодня\n"
                         "/signal — умные сигналы сегодня\n\n"
                         "Я пишу только на русском.")

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer("🆘 Как пользоваться:\n\n"
                         "/predict Команда1 Команда2 — анализ матча с xG, формой и H2H\n"
                         "/today — список матчей на сегодня\n"
                         "/signal — топ-3 лучших матчей для ставок\n\n"
                         "⚠️ Лимит запросов на бесплатном аккаунте.\n"
                         "Если бот пишет «Ваш аккаунт заблокирован» — подними тариф.\n\n"
                         "Все ответы на русском.")

@dp.message(Command("predict"))
async def cmd_predict(message: types.Message):
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.answer("❗ Пример: /predict Спартак Зенит")
        return
    
    team1, team2 = args[1], args[2]
    await message.answer(f"🔍 Анализиваю матч {team1} vs {team2} с xG...")

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

@dp.message(Command("today"))
async def cmd_today(message: types.Message):
    await message.answer("📅 Загружаю матчи на сегодня...")
    async with ClientSession() as session:
        matches = await get_today_matches(session)
    
    if not matches:
        await message.answer("Сегодня матчей нет или API не ответил.")
        return

    text = "📅 **Матчи сегодня (NS)**\n\n"
    for match in matches:
        teams = match["teams"]
        text += f"⚽ {teams['home']['name']} vs {teams['away']['name']}\n🕒 {match['fixture']['date'][:16]}\n\n"
    
    await message.answer(text + "⚠️ xG будет в анализе при /predict")

@dp.message(Command("signal"))
async def cmd_signal(message: types.Message):
    await message.answer("🔥 Генерирую умный сигнал с xG, Value и H2H...")

    async with ClientSession() as session:
        matches = await get_today_matches(session)
    
    if not matches:
        await message.answer("Нет матчей сегодня.")
        return

    signals = []
    for match in matches:
        home_name = match["teams"]["home"]["name"]
        away_name = match["teams"]["away"]["name"]
        result, _ = await analyze_match(home_name, away_name)
        
        if not result:
            continue
        
        score = result["confidence"]
        xg_bonus = abs(result["xg_diff"]) * 15
        value_bonus = abs(result["value"]) * 25
        h2h_bonus = abs(result["h2g_diff"]) * 10
        total_score = score + xg_bonus + value_bonus + h2h_bonus
        
        if total_score > 45:
            signals.append((total_score, result, match))

    if not signals:
        await message.answer("Сегодня нет сильных xG-сигналов.")
        return

    signals.sort(reverse=True, key=lambda x: x[0])
    top3 = signals[:3]

    text = "🔥 **УМНЫЙ ТОП-3 СИГНАЛА ДЛЯ СТАВОК СЕГОДНЯ**\n\n"
    for i, (_, result, m) in enumerate(top3, 1):
        teams = m["teams"]
        text += f"{i}. {teams['home']['name']} vs {teams['away']['name']}\n"
        text += f"   Прогноз: {result['prediction']}\n"
        text += f"   xG: {result['team1']} {result['xG1']} — {result['team2']} {result['xG2']} (разница {result['xg_diff']:+.1f})\n"
        text += f"   Value: {result['value']:+.2f} | H2H xG: {result['h2g_diff']:+.2f}\n"
        text += f"   Уверенность: {result['confidence']}%\n\n"

    text += "⚠️ Это value + xG + исторический H2G. Играйте ответственно."
    await message.answer(text)

@dp.message(F.text)
async def echo_handler(message: types.Message):
    text = message.text.lower()
    is_russian = any(char in text for char in "йцукенгшщзхъфывапролджэячсмитьбю")
    
    if not is_russian:
        await message.answer("Пожалуйста, используйте русский язык. Используй /help")
        return
    
    await message.answer("Напиши /help для списка команд")

# Веб-сервер
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
