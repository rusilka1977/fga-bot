import os
import discord
from discord.ext import tasks, commands
import aiohttp
from datetime import datetime, timedelta, timezone
import time
import asyncio
from flask import Flask

# ----------------- [기본 설정] -----------------
CHANNEL_ID = 1521217489134948433  
SEARCH_KEYWORD = "ord"  # 💡 대소문자 무관, 앞뒤 공백 자동 제거
# ----------------------------------------------

app = Flask(__name__)

@app.route('/')
def home():
    return "FGA Bot Status: Online and Stable"

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
previous_games = {} 
created_room_messages = {}     

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime('%Y-%m-%d %H:%M:%S'), now

@bot.event
async def on_ready():
    # 💡 이제 스레드 락이 없으므로 이 로그가 무조건 찍힙니다!
    print(f"⚙️ [구동 성공] {bot.user.name} 봇이 완전히 로드되었습니다.")
    
    if not monitor_gamelist.is_running():
        monitor_gamelist.start()
        print("[시스템] 대기실 스캔 루프 기동 완료.")
        
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, _ = get_now_strings()
        embed = discord.Embed(
            title="🔄 FGA 모니터링 시작 (엔진 정상화)",
            description=f"• 감시 키워드: **{SEARCH_KEYWORD}**\n• 단일 비동기 코어 전환 완료 🚀",
            color=0x2ecc71
        )
        await channel.send(embed=embed)

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, created_room_messages
    
    target_keyword = SEARCH_KEYWORD.strip().lower()
    print(f"[스캔 리포트] {datetime.now().strftime('%H:%M:%S')} -> '{target_keyword}' 검색 중")

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    url = "https://api.wc3stats.com/gamelist"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            target_url = f"{url}?t={int(time.time())}"
            async with session.get(target_url, headers=headers) as response:
                if response.status != 200:
                    print(f"[로그] API 에러: {response.status}")
                    return

                data = await response.json()
                games = data.get('body', [])
                if not isinstance(games, list):
                    return

                current_games = {}

                for game in games:
                    if not isinstance(game, dict):
                        continue
                    
                    name = str(game.get('name', '')).strip()
                    map_name = str(game.get('map', '')).strip()
                    
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

                print(f"[필터 데이터] 매칭 방: {len(current_games)}개 / 전체 공방: {len(games)}개")

                current_game_ids = set(current_games.keys())
                previous_game_ids = set(previous_games.keys())

                # [새 방 알림]
                for g_id in current_game_ids:
                    if g_id not in previous_game_ids:
                        game_info = current_games[g_id]
                        embed = discord.Embed(
                            title="🆕 새 대기실 생성!", 
                            description=f"**방 제목:** {game_info['name']}\n• 방장: {game_info['host']} ({game_info['current_slots']}/{game_info['max_slots']})", 
                            color=0x2ecc71
                        )
                        sent_msg = await channel.send(content="🆕 **[대기실 생성]**", embed=embed)
                        created_room_messages[g_id] = sent_msg
                        await asyncio.sleep(0.2)

                # [종료된 방 삭제]
                started_games = previous_game_ids - current_game_ids
                for g_id in started_games:
                    if g_id in created_room_messages:
                        try: await created_room_messages[g_id].delete()
                        except: pass
                        finally: del created_room_messages[g_id]

                previous_games = current_games
                
    except Exception as e:
        print(f"[스캔 오류]: {e}")

# 💡 [구조 혁신] Flask 웹서버를 비동기 루프 내에서 가볍게 실행하는 방식
async def run_flask():
    from werkzeug.serving import make_server
    port = int(os.getenv("PORT", 10000))
    # Flask 서버를 비동기 이벤트 루프 방해 없이 완전히 녹여냄
    server = make_server('0.0.0.0', port, app)
    loop = asyncio.get_event_loop()
    print("▶ [웹 서버] 비동기 포트 바인딩 완료 (Port 10000)")
    await loop.run_in_executor(None, server.serve_forever)

async def main():
    # Flask와 디스코드를 단일 비동기 루프에서 동시에 실행
    await asyncio.gather(
        bot.start(TOKEN),
        run_flask()
    )

if __name__ == "__main__":
    asyncio.run(main()
