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
RENDER_APP_NAME = "fga-bot" # 본인의 렌더 앱 이름 확인 필수!
CHANNEL_ID = 1521217489134948433  # 유저님의 디스코드 채널 ID
# --------------------------------------------------

app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running perfectly!"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)

def keep_alive_ping():
    time.sleep(20)
    url = f"https://{RENDER_APP_NAME}.onrender.com/"
    while True:
        try:
            res = requests.get(url)
            print(f"[Self-Ping] 서버 생존 신호 전송 완료. 상태코드: {res.status_code}")
        except Exception as e:
            print(f"[Self-Ping] 에러 발생 (무시 가능): {e}")
        time.sleep(600)
# ------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

TOKEN = os.getenv("TOKEN")          
SEARCH_KEYWORD = "ord"                

previous_games = {} 
is_first_run = True

# ★ 메시지 추적 장부
created_room_messages = {}     # 대기실(초록) 메시지 저장용 {g_id: message_obj}
started_room_messages = {}     # 시작(파란)/폭파(빨간) 메시지 저장용 {room_host: message_obj}

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    text_time = now.strftime('%Y-%m-%d %H:%M:%S')
    return text_time, now

@bot.event
async def on_ready():
    print(f"★ [로그인 성공] {bot.user.name} 봇이 디스코드에 접속했습니다!")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, now_obj = get_now_strings()
        try:
            embed = discord.Embed(
                title="🤖 FGA 모니터링 가동",
                description="• 대기실 스캔 주기: **10초**\n• 실시간 인원 동기화 🔄\n• 안정화 부스터 가동 완료 🚀",
                color=0x2ecc71
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
            print("[디버그] 디스코드 채널로 가동 인사말 전송 완료")
        except Exception as e:
            print(f"[경고] 로그인 인사말 디코 발송 실패: {e}")

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run
    global created_room_messages, started_room_messages
    
    print(f"[디버그 루프] {datetime.now().strftime('%H:%M:%S')} - 스캔 시작")

    if not bot.is_ready():
        print("[디버그 루프] 봇이 아직 디스코드에 완전히 로그인되지 않아 대기합니다.")
        return

    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        print(f"[디버그 에러] 지정된 CHANNEL_ID({CHANNEL_ID})를 찾을 수 없습니다.")
        return

    url = "https://api.wc3stats.com/gamelist"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*"
    }

    try:
        # 동기 방식의 requests를 비동기 루프를 방해하지 않도록 executor에서 실행 (루프 멈춤 방지 핵심)
        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, lambda: requests.get(url, headers=headers, timeout=5))
        
        if "challenge-platform" in response.text or response.status_code != 200:
            print(f"[경고] API 서버 통신 실패(Cloudflare 우회 차단). 다음 주기를 기다립니다.")
            return

        data = response.json()
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

        print(f"[디버그 필터] 전체 방: {len(games)}개 / '{keyword}' 검색된 방: {len(current_games)}개")

        current_game_ids = set(current_games.keys())
        previous_game_ids = set(previous_games.keys())

        if is_first_run:
            previous_games = current_games
            is_first_run = False
            print(f"★ [성공] 최초 방 목록 {len(current_games)}개 장부 등록 완료 (초기 구동 폭탄 알림 방지)")
            return # 첫 실행 시 기존에 있던 수십 개의 방을 한 번에 다 보내면 무조건 차단되므로 첫 스캔은 저장만 하고 넘깁니다.

        # [사라진 방 감지]
        started_games = previous_game_ids - current_game_ids
        for g_id in started_games:
            old_game_info = previous_games[g_id]
            clean_name = old_game_info['name']
            last_slots = old_game_info['current_slots'] 
            room_host = old_game_info['host'] 
            
            if g_id in created_room_messages:
                try: 
                    await created_room_messages[g_id].delete()
                    await asyncio.sleep(0.3) # 레이트 리밋 방지 짧은 대기
                except: pass
                finally: 
                    if g_id in created_room_messages:
                        del created_room_messages[g_id]
            
            if last_slots <= 0:
                if room_host in started_room_messages:
                    del started_room_messages[room_host]
                continue

            if room_host in started_room_messages:
                try:
                    await started_room_messages[room_host].delete()
                    await asyncio.sleep(0.3)
                except: pass
                finally:
                    if room_host in started_room_messages:
                        del started_room_messages[room_host]
            
            text_time, now_obj = get_now_strings()
            
            if last_slots >= 10:
                msg = f"🎮 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 게임을 시작했습니다! ({last_slots}/12)"
                embed = discord.Embed(description=msg, color=0x3498db)
                embed.set_footer(text=f"시작 시각: {text_time} (1시간 후 자동 삭제)")
                try: 
                    sent_msg = await channel.send(content="🎮 **[게임 시작]**", embed=embed, delete_after=3600)
                    started_room_messages[room_host] = sent_msg
                    await asyncio.sleep(0.5) 
                except discord.HTTPException as e:
                    print(f"[디코드 에러] 시작 메시지 송신 실패 (속도 제한 우려): {e}")
            else:
                msg = f"💥 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 **폭파되었거나 대기실이 닫혔습니다.** ({last_slots}/12)"
                embed = discord.Embed(description=msg, color=0xe74c3c)
                embed.set_footer(text=f"폭파 시각: {text_time} (5분 후 자동 삭제)")
                try: 
                    sent_msg = await channel.send(content="💥 **[대기실 폭파]**", embed=embed, delete_after=300)
                    started_room_messages[room_host] = sent_msg
                    await asyncio.sleep(0.5) 
                except discord.HTTPException as e:
                    print(f"[디코드 에러] 폭파 메시지 송신 실패: {e}")

        # [새로 파진 방 및 인원 변경 감지]
        for g_id in current_game_ids:
            game_info = current_games[g_id]
            name = game_info['name']
            current = game_info['current_slots']
            max_slots = game_info['max_slots']
            room_host = game_info['host']
            
            text_time, now_obj = get_now_strings()
            
            if g_id not in previous_game_ids:
                if room_host in started_room_messages:
                    try:
                        await started_room_messages[room_host].delete()
                        await asyncio.sleep(0.3) 
                    except: pass
                    finally:
                        if room_host in started_room_messages:
                            del started_room_messages[room_host]

                embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {room_host} ({current}/{max_slots})", color=0x2ecc71)
                embed.set_footer(text=f"생성 시각: {text_time} (실시간 동기화)")
                try: 
                    sent_msg = await channel.send(content="🆕 **[대기실 생성]**", embed=embed)
                    created_room_messages[g_id] = sent_msg
                    await asyncio.sleep(0.5) 
                except discord.HTTPException as e:
                    print(f"[디코드 에러] 생성 메시지 송신 실패: {e}")
            
            else:
                old_game_info = previous_games[g_id]
                if old_game_info['current_slots'] != current:
                    if g_id in created_room_messages:
                        try:
                            new_embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {room_host} (**{current}**/{max_slots})", color=0x2ecc71)
                            new_embed.set_footer(text=f"인원 갱신: {text_time} (실시간 동기화)")
                            
                            await created_room_messages[g_id].edit(content="🆕 **[대기실 생성]**", embed=new_embed)
                            await asyncio.sleep(0.3) 
                        except: pass

        previous_games = current_games
        
    except Exception as e:
        print(f"[루프 내 예외 발생]: {e}")

async def main_start():
    monitor_gamelist.start()
    await bot.start(TOKEN)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    ping_thread = threading.Thread(target=keep_alive_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    asyncio.run(main_start())
