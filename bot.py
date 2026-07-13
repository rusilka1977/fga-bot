import os
import discord
from discord.ext import tasks, commands
import aiohttp
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
def home(): return "Bot is running perfectly!"
def run_flask():
    app.run(host='0.0.0.0', port=int(os.getenv("PORT", 10000)), use_reloader=False, threaded=True)

import requests
def keep_alive_ping():
    time.sleep(30)
    while True:
        try: requests.get(f"https://{RENDER_APP_NAME}.onrender.com/", timeout=5)
        except: pass
        time.sleep(600)

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
SEARCH_KEYWORD = "ord"               

active_rooms = {}  
is_first_run = True

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    return now.strftime('%Y-%m-%d %H:%M:%S'), now

@bot.event
async def setup_hook():
    monitor_gamelist.start()

@bot.event
async def on_ready():
    print(f"=========================================", flush=True)
    print(f"✅ [구동 성공] {bot.user.name} 봇 감시 엔진 가동 시작", flush=True)
    print(f"=========================================", flush=True)

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global active_rooms, is_first_run
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel: return

    url = "https://api.wc3stats.com/gamelist"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200: return
                data = await response.json()
                
        # 최신 API 반영 (배열 직접 읽기)
        games = data if isinstance(data, list) else data.get('body', [])
        if not isinstance(games, list): return

        fetched_rooms = {}
        keyword = SEARCH_KEYWORD.lower()

        for game in games:
            if not isinstance(game, dict): continue
            
            name = str(game.get('name', ''))
            host = str(game.get('host', 'unknown'))
            map_name = str(game.get('map', ''))
            
            # 대소문자 미스매치 방지를 위해 전부 소문자화 후 비교
            if not keyword or keyword in name.lower() or keyword in map_name.lower():
                # [유저 요청 반영] 방장 이름과 맵 이름을 조합하여 고유 ID 생성
                # 방 제목이 미세하게 바뀌어도 맵 파일명이 같으면 동일한 대기실로 인식합니다.
                game_id = f"{host}_{map_name}"
                
                slots_taken = game.get('slotstaken', game.get('slotsTaken', 0))
                slots_total = game.get('slotstotal', game.get('slotsTotal', 12))
                
                fetched_rooms[game_id] = {
                    'name': name,
                    'map': map_name,
                    'host': host,
                    'current_slots': slots_taken,
                    'max_slots': slots_total
                }

        # 1. 첫 실행 시 초기 기준점 등록 (최초 기동 시 도배 방지)
        if is_first_run:
            for gid, info in fetched_rooms.items():
                active_rooms[gid] = {**info, 'msg_obj': None}
            is_first_run = False
            print(f"★ [성공] 맵 기준 추적 장부 세팅 완료. (현재 {len(active_rooms)}개 방 감시 중)", flush=True)
            return

        text_time, _ = get_now_strings()

        # 2. 신규 생성 및 인원 변경 처리
        for gid, incoming in fetched_rooms.items():
            if gid not in active_rooms:
                embed = discord.Embed(
                    title="🆕 새 대기실 생성!", 
                    description=f"**방 제목:** {incoming['name']}\n• 맵: `{incoming['map']}`\n• 방장: {incoming['host']} ({incoming['current_slots']}/{incoming['max_slots']})", 
                    color=0x2ecc71
                )
                embed.set_footer(text=f"생성 시각: {text_time} (실시간 동기화)")
                try:
                    sent_msg = await channel.send(content="🆕 **[대기실 생성]**", embed=embed)
                    active_rooms[gid] = {**incoming, 'msg_obj': sent_msg}
                    print(f"[디버그] 새 방 생성 알림 완료: {incoming['name']}", flush=True)
                except Exception as e:
                    print(f"디코 전송 실패: {e}", flush=True)
                    active_rooms[gid] = {**incoming, 'msg_obj': None}
            else:
                existing = active_rooms[gid]
                # 방 제목이나 인원수가 달라졌다면 디코 Embed만 깔끔하게 실시간 업데이트
                if existing['current_slots'] != incoming['current_slots'] or existing['name'] != incoming['name']:
                    active_rooms[gid]['current_slots'] = incoming['current_slots']
                    active_rooms[gid]['name'] = incoming['name']
                    if existing.get('msg_obj'):
                        try:
                            new_embed = discord.Embed(
                                title="🆕 새 대기실 생성!", 
                                description=f"**방 제목:** {incoming['name']}\n• 맵: `{incoming['map']}`\n• 방장: {incoming['host']} (**{incoming['current_slots']}**/{incoming['max_slots']})", 
                                color=0x2ecc71
                            )
                            new_embed.set_footer(text=f"인원 갱신: {text_time}")
                            await existing['msg_obj'].edit(content="🆕 **[대기실 생성]**", embed=new_embed)
                        except: pass

        # 3. 사라진 방 감지 (게임 시작 또는 대기실 폭파)
        for gid in list(active_rooms.keys()):
            if gid not in fetched_rooms:
                dead_room = active_rooms[gid]
                if dead_room.get('msg_obj'):
                    try: 
                        await dead_room['msg_obj'].delete()
                        await asyncio.sleep(0.2)
                    except: pass
                
                final_slots = dead_room['current_slots']
                if final_slots >= 10:
                    embed = discord.Embed(description=f"🎮 **[방장: {dead_room['host']}]**님의 **[{dead_room['name']}]** 방이 게임을 시작했습니다! ({final_slots}/{dead_room['max_slots']})", color=0x3498db)
                    try: await channel.send(content="🎮 **[게임 시작]**", embed=embed, delete_after=3600)
                    except: pass
                else:
                    embed = discord.Embed(description=f"💥 **[방장: {dead_room['host']}]**님의 **[{dead_room['name']}]** 방이 폭파되었습니다. ({final_slots}/{dead_room['max_slots']})", color=0xe74c3c)
                    try: await channel.send(content="💥 **[대기실 폭파]**", embed=embed, delete_after=300)
                    except: pass
                    
                del active_rooms[gid]

    except Exception as e:
        print(f"루프 예외: {e}", flush=True)

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    async with bot: await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
