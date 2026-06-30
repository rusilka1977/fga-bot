import os
import discord
from discord.ext import tasks, commands
import requests
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask
import time

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

# ★ 메시지들을 추적하기 위한 장부 (방 생성 메시지 & 10명 알림 메시지 저장)
created_room_messages = {}
ten_players_messages = {}

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
                description="FGA bot이 클라우드 서버에서 가동되었습니다.\n• 새 방 🆕 및 10명 알림 📢 (방폭/시작 시 즉시 연동 삭제)\n• 시작 🎮 및 폭파 💥 알림 (1시간 10분 후 자동 삭제)",
                color=0x3498db
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"로그인 인사말 디코 발송 실패: {e}")
    monitor_gamelist.start()

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run, notified_milestones, created_room_messages, ten_players_messages
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return

    url = "https://api.wc3stats.com/gamelist"
    try:
        response = requests.get(url)
        if response.status_code != 200:
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

        if is_first_run:
            previous_games = current_games
            is_first_run = False
            print(f"★ 모니터링 가동 중... 현재 대기실 기준점 설정 완료.")
            return

        # [사라진 방 감지] -> '방 생성' 및 '10명 알림' 세트로 동시 삭제 로직!
        started_games = previous_game_ids - current_game_ids
        for g_id in started_games:
            old_game_info = previous_games[g_id]
            clean_name = old_game_info['name']
            last_slots = old_game_info['current_slots'] 
            
            if g_id in notified_milestones:
                del notified_milestones[g_id]
            
            # 1. 기존에 있던 [🆕 새 방 생성 메시지]가 장부에 있다면 삭제
            if g_id in created_room_messages:
                try:
                    await created_room_messages[g_id].delete()
                    print(f"[연동 삭제] {clean_name} 방 종료로 '생성 알림' 삭제 완료.")
                except: pass
                finally: del created_room_messages[g_id]
            
            # 2. 기존에 발생했던 [📢 10명 도달 알림 메시지]가 장부에 있다면 함께 삭제
            if g_id in ten_players_messages:
                try:
                    await ten_players_messages[g_id].delete()
                    print(f"[연동 삭제] {clean_name} 방 종료로 '10명 알림' 삭제 완료.")
                except: pass
                finally: del ten_players_messages[g_id]
            
            text_time, now_obj = get_now_strings()
            
            # 시작/폭파 메시지는 1시간 10분(4200초) 후 자동 삭제됩니다.
            if last_slots == 12:
                msg = f"🎮 **[{clean_name}]** 방이 12명 풀방으로 대기를 마치고 **게임을 시작했습니다!**"
                embed = discord.Embed(description=msg, color=0x3498db)
                embed.set_footer(text=f"시작 시각: {text_time} (1시간 10분 후 삭제)")
                try: 
                    await channel.send(content=f"{msg} (확인: {text_time})", embed=embed, delete_after=4200)
                except: pass
            else:
                msg = f"💥 **[{clean_name}]** 방이 12명을 채우지 못하고 **폭파되었거나 대기실이 닫혔습니다.** ({last_slots}/12)"
                embed = discord.Embed(description=msg, color=0xe74c3c)
                embed.set_footer(text=f"폭파 시각: {text_time} (1시간 10분 후 삭제)")
                try: 
                    await channel.send(content=f"{msg} (확인: {text_time})", embed=embed, delete_after=4200)
                except: pass

        # [새로 파진 방 및 인원 감지]
        for g_id in current_game_ids:
            game_info = current_games[g_id]
            name = game_info['name']
            current = game_info['current_slots']
            max_slots = game_info['max_slots']
            
            text_time, now_obj = get_now_strings()
            
            # [새 방 생성 알림] -> 추적용 장부에 보관
            if g_id not in previous_game_ids:
                msg = f"🆕 **새 대기실 생성!**\n방 제목: {name} | 맵: {game_info['map']} | 방장: {game_info['host']} ({current}/{max_slots})"
                embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {game_info['host']} ({current}/{max_slots})", color=0x2ecc71)
                embed.set_footer(text=f"생성 시각: {text_time} (방 종료 시 삭제)")
                try: 
                    sent_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                    created_room_messages[g_id] = sent_msg
                except: pass
            
            # [10명 도달 알림] -> 추적용 장부에 보관 (방 터지면 지워짐)
            if current == 10:
                if notified_milestones.get(g_id) != current:
                    notified_milestones[g_id] = current
                    msg = f"📢 **🚀 인원 도달 알림!**\n**[{name}]** 대기실에 현재 **10명**이 모였습니다! 즉시 접속을 준비하세요! ({current}/{max_slots})"
                    embed = discord.Embed(description=msg, color=0xf1c40f)
                    embed.set_footer(text=f"감지 시각: {text_time} (방 종료 시 삭제)")
                    try: 
                        sent_ten_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                        ten_players_messages[g_id] = sent_ten_msg
                    except: pass

        previous_games = current_games
    except Exception as e:
        print(f"루프 내 에러 발생: {e}")

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    ping_thread = threading.Thread(target=keep_alive_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    bot.run(TOKEN)
