import asyncio
import logging
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiohttp import web, ClientSession

# ================= НАСТРОЙКИ =================
BOT_TOKEN = "7575444568:AAEHYZMjzWvlUHYbB6-ZkDv8e42xpgpV9YA"
RAPIDAPI_KEY = "0cf379b94fmsh2e9e4e5fbdc2b78p1efe49jsnb7dc15ae2f06"
# =============================================

logging.basicConfig(level=logging.INFO)
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ================= xG + signal МОДУЛИ =================
XG_API = "https://v3.football.api-sports.io/fixtures/statistics"
XG_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "v3.football.api-sports.io"
}

H2H_XG_API = "https://v3.football.api-sports.io/fixtures/headtohead"
H2H_XG_HEADERS = XG_HEADERS.copy()

TODAY_API = "https://v3.football.api-sports.io/fixtures"
TODAY_HEADERS = {
    "X-RapidAPI-Key": RAPIDAPI_KEY,
    "X-RapidAPI-Host": "v3.football.api-sports.io"
}

# ================= ФУНКЦИИ =================
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
    avg_xg = (xg_home + xg_away) / 2
