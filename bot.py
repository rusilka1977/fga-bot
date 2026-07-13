import os
import discord
from discord.ext import tasks, commands
import aiohttp
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

def start_flask_server():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)

def keep_alive_ping():
    time.sleep(30)
    url = f"https://{RENDER_APP_NAME}.onrender.com/"
    while True:
        try:
            import requests
            res = requests.get(url, timeout=3)
            print(f"[Self-Ping] 서버 생존 신호 전송 완료. 상태코드: {res.status_code}")
        except:
            pass
        time.sleep(600)
# ------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
SEARCH_KEYWORD = "ord"                

previous_games = {} 
is_first_run = True  # 첫 구동 확인용

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
                description="• 대기실 스캔 주기: **10초**\n• 실시간 인원 동기화 🔄\n• 첫 로딩 로직 버그 수정 완료 🛠️",
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
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    url = "https://api.wc3stats.com/gamelist"
    rand_val = random.randint(100000, 999999)
    headers = {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.{rand_val} Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Cache-Control": "no-cache, no-store, must-revalidate"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            target_url = f"{url}?t={int(time.time())}"
            async with session.get(target_url, headers=headers) as response:
                
                if response.status != 200:
                    print(f"[경고] API 거부 (상태코드: {response.status})")
                    return

                data = await response.json()
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

                # 💡 [버그 수정 핵심] 첫 실행이더라도 return으로 끊지 않고 밑으로 흘려보내서 첫 방 9개를 디코에 전송하게 만듭니다.
                if is_first_run:
                    is_first_run = False
                    print(f"[디버그] 최초 구동 시 감지된 {len(current_games)}개 방 알림 전송 시작")

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
                            await asyncio.sleep(0.1)
                        except: pass
                        finally:
                            if g_id in created_room_messages: del created_room_messages[g_id]
                    
                    if last_slots <= 0:
                        if room_host in started_room_messages: del started_room_messages[room_host]
                        continue

                    if room_host in started_room_messages:
                        try: 
                            await started_room_messages[room_host].delete()
                            await asyncio.sleep(0.1)
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
                                await asyncio.sleep(0.1)
                            except: pass
                            finally:
                                if room_host in started_room_messages: del started_room_messages[room_host]

                        embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {room_host} ({current}/{max_slots})", color=0x2ecc71)
                        embed.set_footer(text=f"생성시각: {text_time}")
                        try:
                            sent_msg = await channel.send(content="🆕 **[대기실 생성]**", embed=embed)
                            created_room_messages[g_id] = sent_msg
                            await asyncio.sleep(0.2) # 적당한 안전 마진
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
    flask_thread = threading.Thread(target=start_flask_server)
    flask_thread.daemon = True
    flask_thread.start()
    
    ping_thread = threading.Thread(target=keep_alive_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    asyncio.run(main_start())
