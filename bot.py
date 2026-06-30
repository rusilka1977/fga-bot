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
CHANNEL_ID = 1521341044942180434
SEARCH_KEYWORD = "fatega"               

previous_games = {} 
notified_milestones = {} 
is_first_run = True

# ★ 메시지 추적 장부
created_room_messages = {}
ten_players_messages = {}

# [수정] 완료 메시지 장부에 '보낸 메시지 객체'와 '시작/폭파된 기준 시각'을 세트로 저장합니다.
finished_room_messages = {} 

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
                description="FGA bot이 클라우드 서버에서 가동되었습니다.\n• 새 방 🆕 및 10명 알림 📢 (종료 시 즉시 삭제)\n• 다음 방 생성 시 이전 시작/폭파 메시지 즉시 추적 삭제 🧹\n• 게임 시작 🎮 알림 (1분마다 실시간 게임 진행 시간 경과 업데이트!)\n• 폭파 💥 알림 (1시간 10분 후 자동 삭제)",
                color=0x3498db
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"로그인 인사말 디코 발송 실패: {e}")
            
    monitor_gamelist.start()
    update_elapsed_time.start() # [추가] 경과 시간 업데이트 타이머 가동!

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run, notified_milestones
    global created_room_messages, ten_players_messages, finished_room_messages
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

        # [사라진 방 감지]
        started_games = previous_game_ids - current_game_ids
        for g_id in started_games:
            old_game_info = previous_games[g_id]
            clean_name = old_game_info['name']
            last_slots = old_game_info['current_slots'] 
            room_host = old_game_info['host'] 
            
            if g_id in notified_milestones:
                del notified_milestones[g_id]
            
            # 1. 기존 생성 알림 삭제
            if g_id in created_room_messages:
                try: await created_room_messages[g_id].delete()
                except: pass
                finally: del created_room_messages[g_id]
            
            # 2. 기존 10명 알림 삭제
            if g_id in ten_players_messages:
                try: await ten_players_messages[g_id].delete()
                except: pass
                finally: del ten_players_messages[g_id]
            
            text_time, now_obj = get_now_strings()
            
            if last_slots == 12:
                # [수정] 시작 메시지 초기 형태 (0분 경과)
                msg = f"🎮 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 12명 풀방으로 **게임을 시작했습니다!**"
                embed = discord.Embed(description=msg, color=0x3498db)
                embed.set_footer(text=f"시작 시각: {text_time} (0분 경과)")
                try: 
                    sent_fin_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed, delete_after=4200)
                    # 나중에 시간을 수정하기 위해 메시지 객체와 현재 시간 객체를 세트로 저장합니다.
                    finished_room_messages[g_id] = {
                        "message": sent_fin_msg,
                        "start_time": now_obj,
                        "host": room_host,
                        "name": clean_name,
                        "type": "start"
                    }
                except: pass
            else:
                # 방폭 메시지는 실시간 시간 측정이 무의미하므로 기존처럼 고정 처리합니다.
                msg = f"💥 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 **폭파되었거나 대기실이 닫혔습니다.** ({last_slots}/12)"
                embed = discord.Embed(description=msg, color=0xe74c3c)
                embed.set_footer(text=f"폭파 시각: {text_time} (1시간 10분 후 삭제)")
                try: 
                    sent_fin_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed, delete_after=4200)
                    finished_room_messages[g_id] = {
                        "message": sent_fin_msg,
                        "start_time": now_obj,
                        "host": room_host,
                        "name": clean_name,
                        "type": "explode"
                    }
                except: pass

        # [새로 파진 방 및 인원 감지]
        for g_id in current_game_ids:
            game_info = current_games[g_id]
            name = game_info['name']
            current = game_info['current_slots']
            max_slots = game_info['max_slots']
            
            text_time, now_obj = get_now_strings()
            
            if g_id not in previous_game_ids:
                if g_id in finished_room_messages:
                    try:
                        await finished_room_messages[g_id]["message"].delete()
                        print(f"[중복 방장 청소] {name}의 이전 판 결과 메시지를 조기 삭제했습니다.")
                    except: pass
                    finally: del finished_room_messages[g_id]

                msg = f"🆕 **새 대기실 생성!**\n방 제목: {name} | 맵: {game_info['map']} | 방장: {game_info['host']} ({current}/{max_slots})"
                embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {game_info['host']} ({current}/{max_slots})", color=0x2ecc71)
                embed.set_footer(text=f"생성 시각: {text_time} (방 종료 시 삭제)")
                try: 
                    sent_msg = await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                    created_room_messages[g_id] = sent_msg
                except: pass
            
            # [10명 도달 알림]
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

# ────────────────────────────────────────────────────────
# 🔥 [핵심 추가] 1분마다 켜져 있는 시작 메시지들의 하단 문구를 수정하는 루프
@tasks.loop(minutes=1)
async def update_elapsed_time():
    global finished_room_messages
    text_time, now_obj = get_now_strings()
    
    # 딕셔너리 순회 도중 삭제 에러 방지를 위해 key 복사본 생성
    targets = list(finished_room_messages.keys())
    
    for g_id in targets:
        room_data = finished_room_messages.get(g_id)
        if not room_data or room_data["type"] != "start":
            continue # 폭파된 방은 수정 안 하고 통과
            
        try:
            msg_obj = room_data["message"]
            start_time = room_data["start_time"]
            room_host = room_data["host"]
            clean_name = room_data["name"]
            
            # 시간 차이 계산 (분 단위)
            elapsed_delta = now_obj - start_time
            elapsed_minutes = int(elapsed_delta.total_seconds() // 60)
            
            # 1시간 10분(70분)이 지나 디코가 자동 삭제했을 시간이면 장부에서 제외
            if elapsed_minutes >= 70:
                if g_id in finished_room_messages:
                    del finished_room_messages[g_id]
                continue
            
            # 메시지 내용과 하단 꼬리말(Embed Footer) 업데이트
            msg = f"🎮 **[방장: {room_host}]**님의 **[{clean_name}]** 방이 12명 풀방으로 **게임을 시작했습니다!**"
            new_embed = discord.Embed(description=msg, color=0x3498db)
            
            # 원래 시작 시각 텍스트 추출용
            orig_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')
            new_embed.set_footer(text=f"시작 시각: {orig_time_str} ({elapsed_minutes}분 경과 🔥)")
            
            # 원격으로 기존 메시지 내용 교체(수정)
            await msg_obj.edit(embed=new_embed)
            print(f"[시간 업데이트] {clean_name} -> {elapsed_minutes}분 경과로 수정됨.")
            
        except discord.errors.NotFound:
            # 유저가 수동으로 지웠거나 다음 방 생성으로 청소된 경우 장부에서 삭제
            if g_id in finished_room_messages:
                del finished_room_messages[g_id]
        except Exception as e:
            print(f"시간 업데이트 중 예외 발생: {e}")
# ────────────────────────────────────────────────────────

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    ping_thread = threading.Thread(target=keep_alive_ping)
    ping_thread.daemon = True
    ping_thread.start()
    
    bot.run(TOKEN)
