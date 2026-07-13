import os
import discord
from discord.ext import tasks, commands
import requests
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask
import time
import asyncio

# ----------------- [설정해 주세요!] -----------------
RENDER_APP_NAME = "fga-bot" 
CHANNEL_ID = 1521217489134948433  
# --------------------------------------------------

app = Flask(__name__)

@app.route('/')
def home():
    return "Diagnostic Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
SEARCH_KEYWORD = "ord"                

previous_games = {} 
is_first_run = True
created_room_messages = {}     

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime('%Y-%m-%d %H:%M:%S'), now

@bot.event
async def on_ready():
    print(f"★ [디스코드 접속 성공] {bot.user.name}")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, _ = get_now_strings()
        try:
            embed = discord.Embed(
                title="🔍 FGA API 정밀 진단 모드 가동",
                description="• 10초 주기로 워크3 API 서버의 원본 데이터를 분석합니다.\n• Render 콘솔 로그를 확인해 주세요.",
                color=0xe67e22
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"가동 메세지 실패: {e}")

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run, created_room_messages
    
    print(f"\n[디버그 루프] {datetime.now().strftime('%H:%M:%S')} - 스캔 시작")

    if not bot.is_ready():
        print("[디버그] 디스코드 연결 대기 중...")
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    # 캐시 방지용 무작위 주소 생성
    url = f"https://api.wc3stats.com/gamelist?t={int(time.time())}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }

    try:
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=5))
        
        print(f"[디버그 API] 응답 상태코드: {response.status_code}")
        
        # 🚨 [핵심] API가 던져주는 원본 데이터의 앞부분 800글자를 강제로 로그에 출력합니다.
        print(f"🚨 [API 원본 데이터 출력]: {response.text[:800]}")

        data = response.json()
        
        # 만약 결과가 딕셔너리가 아니라 리스트로 바로 온다면 구조 변경 처리
        if isinstance(data, list):
            games = data
            print("[구조 진단] API 데이터가 body 없이 리스트([]) 형태로 바로 들어옵니다.")
        else:
            games = data.get('body', [])
            print(f"[구조 진단] API 데이터가 기존 딕셔너리 형태입니다. (body 내부 방 개수: {len(games)}개)")

        if not isinstance(games, list) or len(games) == 0:
            print("[경고] 읽어온 방 목록이 비어있거나 리스트가 아닙니다.")
            return

        current_games = {}
        keyword = SEARCH_KEYWORD.lower()

        # 첫 번째 방 데이터 구조 샘플 분석용
        if len(games) > 0:
            print(f"🔍 [방 한 개의 샘플 데이터 구조]: {games[0]}")

        for game in games:
            if not isinstance(game, dict):
                continue
            
            # API 변경 대비 다중 필드 체크
            name = game.get('name', game.get('name', ''))
            map_name = game.get('map', game.get('mapName', game.get('map_name', '')))
            
            if keyword in name.lower() or keyword in map_name.lower():
                host = game.get('host', 'unknown')
                game_id = f"{host}_{name}"
                current_games[game_id] = {
                    'name': name,
                    'map': map_name,
                    'host': host,
                    'current_slots': game.get('slotsTaken', game.get('players', 0)),
                    'max_slots': game.get('slotsTotal', game.get('maxPlayers', 12))
                }

        print(f"[디버그 필터] '{keyword}' 키워드로 필터링된 방 개수: {len(current_games)}개")

        current_game_ids = set(current_games.keys())
        previous_game_ids = set(previous_games.keys())

        # 디버깅을 위해 최초 가동 차단 기능을 풀고 바로 디코에 쏘도록 수정
        if is_first_run:
            previous_games = current_games
            is_first_run = False
            print("★ 초기 장부 설정 완료 (새 방 생성을 기다립니다)")

        # [새 방 감지 및 디코 발송]
        for g_id in current_game_ids:
            if g_id not in previous_game_ids:
                game_info = current_games[g_id]
                text_time, _ = get_now_strings()
                
                embed = discord.Embed(
                    title="🆕 새 대기실 생성!", 
                    description=f"**방 제목:** {game_info['name']}\n• 맵: `{game_info['map']}`\n• 방장: {game_info['host']} ({game_info['current_slots']}/{game_info['max_slots']})", 
                    color=0x2ecc71
                )
                embed.set_footer(text=f"생성시각: {text_time}")
                try:
                    sent_msg = await channel.send(content="🆕 **[대기실 생성]**", embed=embed)
                    created_room_messages[g_id] = sent_msg
                    print(f"[디스코드 알림 발송 성공] 방 제목: {game_info['name']}")
                except Exception as e:
                    print(f"[디스코드 발송 에러]: {e}")

        previous_games = current_games
    except Exception as e:
        print(f"[루프 내 에러 발생]: {e}")

async def main_start():
    monitor_gamelist.start()
    await bot.start(TOKEN)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    asyncio.run(main_start())
