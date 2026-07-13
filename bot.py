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
SEARCH_KEYWORD = "ord"  # 💡 찾고 싶은 키워드
# ----------------------------------------------

app = Flask(__name__)

@app.route('/')
def home():
    return "FGA Bot Server is Running Fine!"

def start_flask_server():
    port = int(os.getenv("PORT", 10000))
    # use_reloader=False를 주어 메인 프로세스를 방해하지 않음
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

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
    print(f"⚙️ [구동 완료] {bot.user.name} 봇이 로그인되었습니다.")
    
    # 💡 [안전 장치] 비동기 루프가 확실히 실행된 후(on_ready) 스캔 루프를 시작합니다.
    if not monitor_gamelist.is_running():
        monitor_gamelist.start()
        print("[시스템] 대기실 스캔 루프 가동 시작.")
        
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, _ = get_now_strings()
        embed = discord.Embed(
            title="🔄 FGA 모니터링 시작",
            description=f"• 감시 키워드: **{SEARCH_KEYWORD}**\n• 에러 복구 및 정상 스캔 모드 가동",
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

    # 💡 둘 다 테스트해볼 수 있도록 기본 주소로 복귀 (안되면 /war3/gamelist로 교체 가능)
    url = "https://api.wc3stats.com/gamelist"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            # 캐시 방지 타임스탬프 추가
            target_url = f"{url}?t={int(time.time())}"
            async with session.get(target_url, headers=headers) as response:
                if response.status != 200:
                    print(f"[로그] API 서버 에러 코드: {response.status}")
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
                    
                    # 대소문자 구분 없이 매칭 검사 (키워드가 비어있으면 전체 검색)
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

                # [종료/시작된 방 삭제]
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
        print(f"[스캔 내부 오류]: {e}")

if __name__ == "__main__":
    # 1. 웹 서버(Flask)를 단순 백그라운드 스레드로 실행 (독점 방지)
    flask_thread = threading.Thread(target=start_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    
    # 2. 메인 스레드는 오직 디스코드 비동기 엔진 구동에만 전념
    bot.run(TOKEN)
