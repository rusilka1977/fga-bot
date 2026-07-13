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
bot_loop = None  # 비동기 루프를 스레드 간 공유하기 위한 전역 변수

@app.route('/')
def home():
    return "FGA Bot is running perfectly on Main Thread!"

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
    print(f"★ [디스코드 로그인 성공] {bot.user.name}")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, _ = get_now_strings()
        try:
            embed = discord.Embed(
                title="🤖 FGA 모니터링 가동",
                description="• 대기실 스캔 주기: **10초**\n• 인원 동기화 및 메인 스레드 스위칭 완벽 적용 ⚡",
                color=0x2ecc71
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"가동 메세지 실패: {e}")

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run
    global created_room_messages, started_room_messages
    
    print(f"[루프 작동 체크] {datetime.now().strftime('%H:%M:%S')} - 정상 스캔 중")

    if not bot.is_ready():
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    url = "https://api.wc3stats.com/gamelist"
    rand_val = random.randint(100000, 999999)
    headers = {
        "User-Agent": f"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.{rand_val} Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=4)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            target_url = f"{url}?t={int(time.time())}"
            async with session.get(target_url, headers=headers) as response:
                if response.status != 200:
                    return

                data = await response.json()
                games = data.get('body', [])
                if not isinstance(games, list):
                    return

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

                # 💡 [핵심 패치 1] 최초 구동 시 9개 방을 메시지 9개로 쪼개 보내지 않고, 1개의 Embed로 묶어서 단 한 번만 전송
                if is_first_run:
                    is_first_run = False
                    if current_games:
                        text_time, _ = get_now_strings()
                        embed = discord.Embed(title="🆕 현재 개설된 대기실 목록", color=0x2ecc71)
                        for g_id, g_info in current_games.items():
                            embed.add_field(
                                name=g_info['name'], 
                                value=f"• 방장: {g_info['host']} ({g_info['current_slots']}/{g_info['max_slots']})", 
                                inline=False
                            )
                        embed.set_footer(text=f"동기화 시각: {text_time}")
                        
                        # 딱 한 번만 전송하여 네트워크 부하를 최소화
                        sent_msg = await channel.send(content="🆕 **[현재 대기실 상황]**", embed=embed)
                        
                        # 추후 인원 변경 감지를 위해 등록
                        for g_id in current_games.keys():
                            created_room_messages[g_id] = sent_msg
                            
                    previous_games = current_games
                    print(f"[디버그] 최초 {len(current_games)}개 방 통합 전송 및 기준점 등록 완료.")
                    return

                # [방 퇴장/시작/폭파 감지]
                started_games = previous_game_ids - current_game_ids
                for g_id in started_games:
                    old_game_info = previous_games[g_id]
                    clean_name = old_game_info['name']
                    last_slots = old_game_info['current_slots']
                    room_host = old_game_info['host']
                    
                    # 만약 첫 통합 메시지에 포함된 방이라면 삭제는 스킵하고 장부에서만 정리
                    if g_id in created_room_messages and created_room_messages[g_id].embeds and len(created_room_messages[g_id].embeds)[0].title == "🆕 현재 개설된 대기실 목록":
                        pass
                    elif g_id in created_room_messages:
                        try: await created_room_messages[g_id].delete()
                        except: pass
                        finally: del created_room_messages[g_id]
                    
                    if last_slots <= 0:
                        if room_host in started_room_messages: del started_room_messages[room_host]
                        continue
                    
                    text_time, _ = get_now_strings()
                    if last_slots >= 10:
                        embed = discord.Embed(description=f"🎮 **[방장: {room_host}]**님의 **[{clean_name}]** 방 게임 시작! ({last_slots}/12)", color=0x3498db)
                        try: await channel.send(content="🎮 **[게임 시작]**", embed=embed, delete_after=3600)
                        except: pass
                    else:
                        embed = discord.Embed(description=f"💥 **[방장: {room_host}]**님의 **[{clean_name}]** 방 폭파 또는 종료 ({last_slots}/12)", color=0xe74c3c)
                        try: await channel.send(content="💥 **[대기실 폭파]**", embed=embed, delete_after=300)
                        except: pass

                # [새 방 감지 및 인원 변경]
                for g_id in current_game_ids:
                    game_info = current_games[g_id]
                    if g_id not in previous_game_ids:
                        embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {game_info['name']}\n• 방장: {game_info['host']} ({game_info['current_slots']}/{game_info['max_slots']})", color=0x2ecc71)
                        try:
                            sent_msg = await channel.send(content="🆕 **[대기실 생성]**", embed=embed)
                            created_room_messages[g_id] = sent_msg
                        except: pass
                    else:
                        old_info = previous_games[g_id]
                        if old_info['current_slots'] != game_info['current_slots']:
                            # 첫 통합 메시지에 속한 방이 아닐 때만 수정 시도
                            if g_id in created_room_messages and created_room_messages[g_id].embeds and created_room_messages[g_id].embeds[0].title != "🆕 현재 개설된 대기실 목록":
                                try:
                                    new_embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {game_info['name']}\n• 방장: {game_info['host']} (**{game_info['current_slots']}**/{game_info['max_slots']})", color=0x2ecc71)
                                    await created_room_messages[g_id].edit(content="🆕 **[대기실 생성]**", embed=new_embed)
                                except: pass

                previous_games = current_games
    except Exception as e:
        print(f"[오류]: {e}")

# 💡 [핵심 패치 2] 디스코드 봇 구동을 백그라운드 전용 스레드로 완전 격리
def run_discord_bot():
    global bot_loop
    bot_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(bot_loop)
    
    monitor_gamelist.start()
    
    try:
        bot_loop.run_until_complete(bot.start(TOKEN))
    except Exception as e:
        print(f"[디스코드 스레드 종료]: {e}")

if __name__ == "__main__":
    # 1. 디스코드 봇 스레드 가동
    discord_thread = threading.Thread(target=run_discord_bot)
    discord_thread.daemon = True
    discord_thread.start()
    
    # 2. 파이썬 프로세스의 메인 주도권을 Flask 웹 서버가 가지도록 설정 (Render 최적화)
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, threaded=True, use_reloader=False)
