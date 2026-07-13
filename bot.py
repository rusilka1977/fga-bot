import os
import discord
from discord.ext import tasks, commands
import aiohttp
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask
import time
import asyncio

# ----------------- [기본 설정] -----------------
CHANNEL_ID = 1521217489134948433  
SEARCH_KEYWORD = "ord"  # 💡 찾고 싶은 키워드 (한글, 영어 대소문자 상관없음)
# ----------------------------------------------

app = Flask(__name__)

@app.route('/')
def home():
    return "FGA Bot Reset Complete!"

def start_flask_server():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
previous_games = {} 
is_first_run = True
created_room_messages = {}     

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime('%Y-%m-%d %H:%M:%S'), now

@bot.event
async def on_ready():
    print(f"⚙️ [초기화 완료] {bot.user.name} 봇이 처음부터 다시 시작합니다.")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, _ = get_now_strings()
        embed = discord.Embed(
            title="🔄 FGA 시스템 초기화 완료",
            description=f"• 감시 키워드: **{SEARCH_KEYWORD}**\n• 새 주소 및 동기화 엔진 리셋 완료",
            color=0xe67e22
        )
        await channel.send(embed=embed)

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run, created_room_messages
    
    target_keyword = SEARCH_KEYWORD.strip().lower()
    print(f"[스캔 리포트] {datetime.now().strftime('%H:%M:%S')} -> 키워드 '{target_keyword}' 추적 중")

    if not bot.is_ready():
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # 💡 [핵심 보정] 오피셜 캐시 파이프라인 주소로 변경하여 원본 유실 방지
    url = "https://api.wc3stats.com/war3/gamelist"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    print(f"[로그] API 서버 응답 에러: {response.status}")
                    return

                data = await response.json()
                games = data.get('body', [])
                if not isinstance(games, list):
                    print("[로그] body 데이터가 올바른 리스트 형식이 아닙니다.")
                    return

                current_games = {}

                for game in games:
                    if not isinstance(game, dict):
                        continue
                    
                    # 제목과 맵 속성을 안전하게 추출
                    name = str(game.get('name', '')).strip()
                    map_name = str(game.get('map', '')).strip()
                    
                    # 검색어 조건 매칭 (키워드가 비어있으면 모든 방 수집)
                    if not target_keyword or (target_keyword in name.lower()) or (target_keyword in map_name.lower()):
                        host = game.get('host', 'unknown')
                        game_id = f"{host}_{name}"
                        current_games[game_id] = {
                            'name': name,
                            'map': map_name,
                            'host': host,
                            'current_slots': game.get('slotsTaken', 0),
                            'max_slots': game.get('slotsTotal', 0)
                        }

                print(f"[필터 데이터] 매칭된 방: {len(current_games)}개 / 배틀넷 전체 방: {len(games)}개")

                current_game_ids = set(current_games.keys())
                previous_game_ids = set(previous_games.keys())

                # 처음 켰을 때 대기실에 있는 방들 일괄 전송
                if is_first_run:
                    is_first_run = False
                    previous_games = current_games
                    if current_games:
                        for g_id, game_info in current_games.items():
                            embed = discord.Embed(
                                title="🆕 대기실 발견 (초기화)", 
                                description=f"**방 제목:** {game_info['name']}\n• 방장: {game_info['host']} ({game_info['current_slots']}/{game_info['max_slots']})", 
                                color=0x34495e
                            )
                            sent_msg = await channel.send(embed=embed)
                            created_room_messages[g_id] = sent_msg
                            await asyncio.sleep(0.2)
                    return

                # [실시간 신규 방 알림]
                for g_id in current_game_ids:
                    if g_id not in previous_game_ids:
                        game_info = current_games[g_id]
                        embed = discord.Embed(
                            title="🆕 새 대기실 생성!", 
                            description=f"**방 제목:** {game_info['name']}\n• 맵: `{game_info['map']}`\n• 방장: {game_info['host']} ({game_info['current_slots']}/{game_info['max_slots']})", 
                            color=0x2ecc71
                        )
                        sent_msg = await channel.send(embed=embed)
                        created_room_messages[g_id] = sent_msg

                # [시작되거나 없어진 방 정리]
                started_games = previous_game_ids - current_game_ids
                for g_id in started_games:
                    if g_id in created_room_messages:
                        try:
                            await created_room_messages[g_id].delete()
                        except:
                            pass
                        finally:
                            del created_room_messages[g_id]

                previous_games = current_games
                
    except Exception as e:
        print(f"[스캔 오류 발생]: {e}")

async def main_start():
    monitor_gamelist.start()
    await bot.start(TOKEN)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    
    asyncio.run(main_start())
