import os
import discord
from discord.ext import tasks, commands
import requests
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask
import time
import asyncio
import random

# ----------------- [설정해 주세요!] -----------------
RENDER_APP_NAME = "fga-bot" 
CHANNEL_ID = 1521217489134948433  
# --------------------------------------------------

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running perfectly!"

# 💡 [구조 변경] Flask 웹 서버가 독립적으로 돌아가도록 완벽히 분리
def start_flask_server():
    port = int(os.getenv("PORT", 10000))
    # Flask 내부에서 일어나는 신호가 메인 비동기 루프를 건들지 못하게 제한
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

def keep_alive_ping():
    time.sleep(30)
    url = f"https://{RENDER_APP_NAME}.onrender.com/"
    while True:
        try:
            res = requests.get(url, timeout=5)
            print(f"[Self-Ping] 서버 생존 신호 전송 완료. 상태코드: {res.status_code}")
        except Exception as e:
            pass
        time.sleep(600)
# ------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
SEARCH_KEYWORD = "ord"                

previous_games = {} 
is_first_run = True

created_room_messages = {}     
started_room_messages = {}     

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime('%Y-%m-%d %H:%M:%S'), now

@bot.event
async def on_ready():
    print(f"★ [디스코드 접속 성공] {bot.user.name} 봇이 연결되었습니다!")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, _ = get_now_strings()
        try:
            embed = discord.Embed(
                title="🤖 FGA 모니터링 가동",
                description="• 대기실 스캔 주기: **10초**\n• 실시간 인원 동기화 🔄\n• 멀티스레드 격리 부스터 가동 ⚡",
                color=0x2ecc71
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[경고] 가동 메세지 전송 실패: {e}")

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run
    global created_room_messages, started_room_messages
    
    print(f"[디버그 루프] {datetime.now().strftime('%H:%M:%S')} - 스캔 가동 중")

    if not bot.is_ready():
        print("[디버그 루프] 디스코드 연결 대기 중...")
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    url = "https://api.wc3stats.com/gamelist"
    rand_val = random.randint(100000, 999999)
    headers = {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.{rand_val} Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cache-Control": "no-cache, no-store, must-revalidate",
        "Pragma": "no-cache"
    }

    try:
        loop = asyncio.get_event_loop()
        target_url = f"{url}?t={int(time.time())}"
        response = await loop.run_in_executor(None, lambda: requests.get(target_url, headers=headers, timeout=5))
        
        if response.status_code != 200 or "challenge-platform" in response.text:
            print(f"[경고] wc3stats API 접근 일시 거부됨 (상태코드: {response.status_code})")
            return

        data = response.json()
        games = data.get('body', [])
        if not isinstance(games, list):
            return

        print(f"[디버그 API] 전체 방: {len(games)}개 감지")

        current_games = {}
        keyword = SEARCH_KEYWORD.lower()

        for game in games:
            if not isinstance(game, dict):
                continue
            name = game.get('name', '')
            map_name = game.get('map', '')
            
            if not keyword or keyword in name.lower() or keyword in map_name.lower():
                host = game.get('host', 'unknown')
                game_id = f"{host}_{name}"
                current_games[game_id] = {
                    'name': name,
                    'map': map_name,
                    'host': host,
                    'current_slots': game.get('slotsTaken', 0),
                    'max_slots': game.get('slotsTotal', 0)
                }

        current_game_ids = set(current_games.keys())
        previous_game_ids = set(previous_games.keys())

        if is_first_run:
            previous_games = current_games
            is_first_run = False
            print(f"[디버그] 초기 기준점 {len(current_games)}개 등록 완료.")

        # [방 퇴장/시작/폭파 감지]
        started_games = previous_game_ids - current_game_ids
        for g_id in started_games:
            old_game_info = previous_games[g_id]
            clean_name = old_game_info['name']
            last_slots = old_game_info['current_slots']
            room_host = old_game_info['host']
            
            if g_id in created_room_messages:
                try: 
                    await created_room_messages[g_id].delete()
                    await asyncio.sleep(0.2)
                except: pass
                finally:
                    if g_id in created_room_messages: del created_room_messages[g_id]
            
            if last_slots <= 0:
                if room_host in started_room_messages: del started_room_messages[room_host]
                continue

            if room_host in started_room_messages:
                try: 
                    await started_room_messages[room_host].delete()
                    await asyncio.sleep(0.2)
                except: pass
                finally:
                    if room_host in started_room_messages: del started_room_messages[room_host]
            
            text_time, _ = get_now_strings()
            if last_slots >= 10:
                embed = discord.Embed(description=f"🎮 **[방장: {room_host}]**님의 **[{clean_name}]** 방 게임 시작! ({last_slots}/12)", color=0x3498db)
                embed.set_footer(text=f"시작시각: {text_time}")
                try:
                    sent_msg = await channel.send(content="🎮 **[게임 시작]**", embed=embed, delete_after=3600)
                    started_room_messages[room_host] = sent_msg
                except: pass
            else:
                embed = discord.Embed(description=f"💥 **[방장: {room_host}]**님의 **[{clean_name}]** 방 폭파 또는 종료 ({last_slots}/12)", color=0xe74c3c)
                embed.set_footer(text=f"폭파시각: {text_time}")
                try:
                    sent_msg = await channel.send(content="💥 **[대기실 폭파]**", embed=embed, delete_after=300)
                    started_room_messages[room_host] = sent_msg
                except: pass

        # [새 방 감지 및 인원 변경]
        for g_id in current_game_ids:
            game_info = current_games[g_id]
            name = game_info['name']
            current = game_info['current_slots']
            max_slots = game_info['max_slots']
            room_host = game_info['host']
            text_time, _ = get_now_strings()
            
            if g_id not in previous_game_ids:
                if room_host in started_room_messages:
                    try: 
                        await started_room_messages[room_host].delete()
                        await asyncio.sleep(0.2)
                    except: pass
                    finally:
                        if room_host in started_room_messages: del started_room_messages[room_host]

                embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {room_host} ({current}/{max_slots})", color=0x2ecc71)
                embed.set_footer(text=f"생성시각: {text_time}")
                try:
                    sent_msg = await channel.send(content="🆕 **[대기실 생성]**", embed=embed)
                    created_room_messages[g_id] = sent_msg
                except: pass
            else:
                old_info = previous_games[g_id]
                if old_info['current_slots'] != current:
                    if g_id in created_room_messages:
                        try:
                            new_embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {room_host} (**{current}**/{max_slots})", color=0x2ecc71)
                            new_embed.set_footer(text=f"갱신시각: {text_time}")
                            await created_room_messages[g_id].edit(content="🆕 **[대기실 생성]**", embed=new_embed)
                        except: pass

        previous_games = current_games
    except Exception as e:
        print(f"[루프 내 예외 발생]: {e}")

async def main_start():
    monitor_gamelist.start()
    await bot.start(TOKEN)

if __name__ == "__main__":
    # 1. Flask 서버를 메인 루프와 완전히 다른 물리 스레드로 격리하여 실행
    flask_thread = threading.Thread(target=start_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    
    # 2. 킵 얼라이브 핑 스레드 실행
    ping_thread = threading.Thread(target=keep_alive_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    # 3. 디스코드 비동기 엔진 독점 구동
    asyncio.run(main_start())
