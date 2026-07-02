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
CHANNEL_ID = 1521217489134948433  
SEARCH_KEYWORD = "fatega"               

previous_games = {} 
notified_milestones = {} 
is_first_run = True

# ★ 메시지 추적 장부
created_room_messages = {}
milestone_messages = {} 
finished_room_by_host = {}

def get_now_strings():
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    text_time = now.strftime('%Y-%m-%d %H:%M:%S')
    return text_time, now

@bot.event
async def on_ready():
    print(f"{bot.user.name} 봇이 성공적으로 로그인했습니다!")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        text_time, now_obj = get_now_strings()
        try:
            embed = discord.Embed(
                title="🤖 워크래프트 3 모니터링 시작",
                description="FGA bot이 불사조 모드로 재가동되었습니다.\n• 동기화 주기: 8초 (우회 헤더 적용) 🛡️\n• 새 방 🆕 및 인원 알림 📢 (종료 시 즉시 삭제)\n• 인원 알림 조건: 10명 도달 시 📢\n• 중복 방장 자동 청소 🧹\n• 게임 시작 🎮 알림 (실시간 시간 표시)\n• 방 폭파 💥 알림 (10분 후 자동 삭제 ⏱️)\n• **초기 구동 예외 처리 완료 (보안벽 면역) 💪**",
                color=0x3498db
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"로그인 인사말 디코 발송 실패: {e}")
            
    monitor_gamelist.start()
    update_elapsed_time.start() 

@tasks.loop(seconds=8)
async def monitor_gamelist():
    global previous_games, is_first_run, notified_milestones
    global created_room_messages, milestone_messages, finished_room_by_host
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    url = "https://api.wc3stats.com/gamelist"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7"
    }

    try:
        response = requests.get(url, headers=headers, timeout=5)
        
        # 🔥 [보완] 클라우드플레어 보안벽이 감지되면 죽지 않고 그냥 return으로 스킵 처리 (8초 뒤 재시도)
        if "challenge-platform" in response.text or response.status_code != 200:
            print(f"[경고] API 서버 보안 인증(Cloudflare) 감지됨. 봇을 유지하고 다음 루프(8초 뒤)에서 재시도합니다.")
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

        current_game_ids = set(current_games.keys())
        previous_game_ids = set(previous_games.keys())

        # 🔥 [핵심 보완] 데이터를 완벽하게 한 번 가져오는 데 성공했을 때만 첫 기준점을 잡음
        if is_first_run:
            previous_games = current_games
            is_first_run = False
            print(f"★ [성공] API 보안벽 우회 통과! 모니터링 기준점이 정상 설정되었습니다.")
            return

        # [사라진 방 감지]
        started_games = previous_game_ids - current_game_ids
        for g_id in started_games:
            old_game_info = previous_games[g_id]
            clean_name = old_game_info['name']
            last_slots = old_game_info['current_slots'] 
            room_host = old_game_info['host'] 
            
            if g_id in notified_milestones:
                del notified_milestones[g_id]
            
            if g_id in created_room_messages:
                try: 
                    await created_room_messages[g_id].delete()
                    await asyncio.sleep(0.5)
                except: pass
                finally: del created_room_messages[g_id]
            
            if g_id in milestone_messages:
                for msg_obj in milestone_messages[g_id]:
                    try: 
                        await msg_obj.delete()
                        await asyncio.sleep(0.5)
                    except: pass
                del milestone_messages[g_id]
            
            text_time, now_obj = get_now_strings()
            
            if last_slots == 12:
                msg = f"🎮 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 12명 풀방으로 **게임을 시작했습니다!**"
                embed = discord.Embed(description=msg, color=0x3498db)
                embed.set_footer(text=f"시작 시각: {text_time} (0분 경과)")
                try: 
                    sent_fin_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed, delete_after=4200)
                    finished_room_by_host[room_host] = {
                        "message": sent_fin_msg,
                        "start_time": now_obj,
                        "name": clean_name,
                        "type": "start"
                    }
                    await asyncio.sleep(0.5)
                except: pass
            else:
                msg = f"💥 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 **폭파되었거나 대기실이 닫혔습니다.** ({last_slots}/12)"
                embed = discord.Embed(description=msg, color=0xe74c3c)
                embed.set_footer(text=f"폭파 시각: {text_time} (10분 후 삭제)")
                try: 
                    sent_fin_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed, delete_after=600)
                    finished_room_by_host[room_host] = {
                        "message": sent_fin_msg,
                        "start_time": now_obj,
                        "name": clean_name,
                        "type": "explode"
                    }
                    await asyncio.sleep(0.5)
                except: pass

        # [새로 파진 방 및 인원 감지]
        for g_id in current_game_ids:
            game_info = current_games[g_id]
            name = game_info['name']
            current = game_info['current_slots']
            max_slots = game_info['max_slots']
            room_host = game_info['host']
            
            text_time, now_obj = get_now_strings()
            
            if g_id not in previous_game_ids:
                if room_host in finished_room_by_host:
                    try:
                        await finished_room_by_host[room_host]["message"].delete()
                        await asyncio.sleep(0.5)
                        print(f"[중복 방장 청소] 방장 {room_host}의 이전 판 결과 메시지를 조기 삭제했습니다.")
                    except: pass
                    finally: del finished_room_by_host[room_host]

                msg = f"🆕 **새 대기실 생성!**\n방 제목: {name} | 맵: {game_info['map']} | 방장: {room_host} ({current}/{max_slots})"
                embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {room_host} ({current}/{max_slots})", color=0x2ecc71)
                embed.set_footer(text=f"생성 시각: {text_time} (방 종료 시 삭제)")
                try: 
                    sent_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                    created_room_messages[g_id] = sent_msg
                    await asyncio.sleep(0.5)
                except: pass
            
            if current == 10:
                if notified_milestones.get(g_id) != current:
                    notified_milestones[g_id] = current
                    
                    msg = f"📢 **🚀 인원 도달 알림!**\n**[{name}]** 대기실에 현재 **10명**이 모였습니다! 즉시 접속을을 준비하세요! ({current}/{max_slots})"
                    embed = discord.Embed(description=msg, color=0xf1c40f)
                    embed.set_footer(text=f"감지 시각: {text_time} (방 종료 시 삭제)")
                    
                    try: 
                        sent_milestone_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                        if g_id not in milestone_messages:
                            milestone_messages[g_id] = []
                        milestone_messages[g_id].append(sent_milestone_msg)
                        await asyncio.sleep(0.5)
                    except: pass

        previous_games = current_games
    except Exception as e:
        print(f"[루프 내 예외 발생 (자동 패스)]: {e}")

# 1분마다 시작 메시지 경과 시간 수정하는 루프
@tasks.loop(minutes=1)
async def update_elapsed_time():
    global finished_room_by_host
    text_time, now_obj = get_now_strings()
    
    hosts = list(finished_room_by_host.keys())
    for room_host in hosts:
        room_data = finished_room_by_host.get(room_host)
        if not room_data:
            continue
            
        if room_data["type"] == "explode":
            start_time = room_data["start_time"]
            elapsed_delta = now_obj - start_time
            if int(elapsed_delta.total_seconds() // 60) >= 10:
                if room_host in finished_room_by_host:
                    del finished_room_by_host[room_host]
            continue 
            
        try:
            msg_obj = room_data["message"]
            start_time = room_data["start_time"]
            clean_name = room_data["name"]
            
            elapsed_delta = now_obj - start_time
            elapsed_minutes = int(elapsed_delta.total_seconds() // 60)
            
            if elapsed_minutes >= 70:
                if room_host in finished_room_by_host:
                    del finished_room_by_host[room_host]
                continue
            
            msg = f"🎮 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 12명 풀방으로 **게임을 시작했습니다!**"
            new_embed = discord.Embed(description=msg, color=0x3498db)
            
            orig_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
            new_embed.set_footer(text=f"시작 시각: {orig_time_str} ({elapsed_minutes}분 경과 🔥)")
            
            await msg_obj.edit(embed=new_embed)
            await asyncio.sleep(0.8)
            
        except discord.errors.NotFound:
            if room_host in finished_room_by_host:
                del finished_room_by_host[room_host]
        except Exception as e:
            print(f"시간 업데이트 중 예외 발생: {e}")

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    ping_thread = threading.Thread(target=keep_alive_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    bot.run(TOKEN)
