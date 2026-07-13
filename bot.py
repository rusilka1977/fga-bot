Python
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
def home():
    return "Bot is running perfectly!"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port, use_reloader=False, threaded=True)

import requests
def keep_alive_ping():
    time.sleep(30)
    url = f"https://{RENDER_APP_NAME}.onrender.com/"
    while True:
        try:
            res = requests.get(url, timeout=5)
            print(f"[Self-Ping] 생존 신호 전송 완료. 상태코드: {res.status_code}", flush=True)
        except Exception as e:
            print(f"[Self-Ping] 에러 발생 (무시 가능): {e}", flush=True)
        time.sleep(600)
# ------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
SEARCH_KEYWORD = "ord"               

active_rooms = {}  
is_first_run = True

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    text_time = now.strftime('%Y-%m-%d %H:%M:%S')
    return text_time, now

@bot.event
async def setup_hook():
    print("⚙️ [시스템] 바뀐 API 기준 모니터링 엔진 로드 중...", flush=True)
    monitor_gamelist.start()

@bot.event
async def on_ready():
    print("=========================================", flush=True)
    print(f"✅ [구동 성공] {bot.user.name} 봇이 모니터링을 시작합니다.")
    print("=========================================", flush=True)
    
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, _ = get_now_strings()
        try:
            embed = discord.Embed(
                title="🤖 FGA 실시간 모니터링 엔진 가동",
                description=f"• 감시 주기: **10초**\n• 필터 키워드: `{SEARCH_KEYWORD}`\n• 상태: **최신 API 연동 완료** 🔄",
                color=0x2ecc71
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"[오류] 초기 알림 발송 실패: {e}", flush=True)

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global active_rooms, is_first_run
    
    await bot.wait_until_ready()
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    url = "https://api.wc3stats.com/gamelist"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "application/json"
    }

    try:
        timeout = aiohttp.ClientTimeout(total=5)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers=headers) as response:
                if response.status != 200:
                    print(f"[경고] API 응답 실패: {response.status}", flush=True)
                    return
                data = await response.json()
                
        # [수정 포인트 1] 데이터가 'body'에 안 감싸져 있고 배열 자체로 들어옴
        games = data if isinstance(data, list) else data.get('body', [])
        if not isinstance(games, list):
            return

        fetched_rooms = {}
        keyword = SEARCH_KEYWORD.lower()

        for game in games:
            if not isinstance(game, dict):
                continue
            
            # 예비 고유 키 조합 생성
            name = game.get('name', game.get('name', ''))
            host = game.get('host', game.get('host', 'unknown'))
            game_id = str(game.get('id', f"{host}_{name}"))
            map_name = game.get('map', game.get('map', ''))
            
            if not keyword or keyword in name.lower() or keyword in map_name.lower():
                # [수정 포인트 2] 대소문자 구분을 없앤 소문자 필드 매칭 (혹시 모를 구버전 호환 유지)
                slots_taken = game.get('slotstaken', game.get('slotsTaken', 0))
                slots_total = game.get('slotstotal', game.get('slotsTotal', 12))
                
                fetched_rooms[game_id] = {
                    'name': name,
                    'map': map_name,
                    'host': host,
                    'current_slots': slots_taken,
                    'max_slots': slots_total
                }

        if is_first_run:
            for gid, info in fetched_rooms.items():
                active_rooms[gid] = {**info, 'msg_obj': None}
            is_first_run = False
            print(f"★ [성공] 최신 API 기준점 로드 완료. (기존 방 {len(active_rooms)}개)", flush=True)
            return

        text_time, _ = get_now_strings()

        # 2. 신규 대기실 생성 및 인원 변경 감지
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
                except Exception as e:
                    print(f"[오류] 생성 알림 실패: {e}", flush=True)
                    active_rooms[gid] = {**incoming, 'msg_obj': None}
            
            else:
                existing = active_rooms[gid]
                if existing['current_slots'] != incoming['current_slots']:
                    active_rooms[gid]['current_slots'] = incoming['current_slots']
                    if existing.get('msg_obj'):
                        try:
                            new_embed = discord.Embed(
                                title="🆕 새 대기실 생성!", 
                                description=f"**방 제목:** {incoming['name']}\n• 맵: `{incoming['map']}`\n• 방장: {incoming['host']} (**{incoming['current_slots']}**/{incoming['max_slots']})", 
                                color=0x2ecc71
                            )
                            new_embed.set_footer(text=f"인원 갱신: {text_time} (실시간 동기화)")
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
                room_host = dead_room['host']
                room_name = dead_room['name']
                
                if final_slots > 0:
                    if final_slots >= 10:
                        msg = f"🎮 **[방장: {room_host}]**님의 **[{room_name}]** 방이 게임을 시작했습니다! ({final_slots}/{dead_room['max_slots']})"
                        embed = discord.Embed(description=msg, color=0x3498db)
                        embed.set_footer(text=f"시작 시각: {text_time} (1시간 후 자동 삭제)")
                        try: await channel.send(content="🎮 **[게임 시작]**", embed=embed, delete_after=3600)
                        except: pass
                    else:
                        msg = f"💥 **[방장: {room_host}]**님의 **[{room_name}]** 방이 **폭파되었거나 대기실이 닫혔습니다.** ({final_slots}/{dead_room['max_slots']})"
                        embed = discord.Embed(description=msg, color=0xe74c3c)
                        embed.set_footer(text=f"폭파 시각: {text_time} (5분 후 자동 삭제)")
                        try: await channel.send(content="💥 **[대기실 폭파]**", embed=embed, delete_after=300)
                        except: pass

                del active_rooms[gid]

    except asyncio.TimeoutError:
        print("[타임아웃] API 서버 응답 지연", flush=True)
    except Exception as e:
        print(f"[루프 에러 발생]: {e}", flush=True)

async def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=keep_alive_ping, daemon=True).start()
    async with bot:
        await bot.start(TOKEN)

if __name__ == "__main__":
    asyncio.run(main())
