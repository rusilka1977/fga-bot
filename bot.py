import os
import discord
from discord.ext import tasks, commands
import requests
from datetime import datetime, timedelta, timezone
import threading
from flask import Flask

# ----------------- [렌더 가상 서버 타임아웃 방지용 가짜 웹서버] -----------------
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    port = int(os.getenv("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
# ------------------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------- [렌더 가상 서버용 안전 설정] -----------------
TOKEN = os.getenv("TOKEN")          
CHANNEL_ID = 1521217489134948433  
SEARCH_KEYWORD = ""               
# -------------------------------------------------------------

previous_games = {} 
notified_milestones = {} 
is_first_run = True

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
                description="FGA bot이 클라우드 서버에서 가동되었습니다.\n• 12인 풀방 시작/방폭 감지\n• 10명 대기실 인원 알림 가동!",
                color=0x3498db
            )
            embed.set_footer(text=f"가동 시각: {text_time}")
            await channel.send(embed=embed)
        except Exception as e:
            print(f"로그인 인사말 디코 발송 실패: {e}")
    monitor_gamelist.start()

@tasks.loop(seconds=10)
async def monitor_gamelist():
    global previous_games, is_first_run, notified_milestones
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
            print(f"★ 모니터링 가동 중... 현재 대기실 기준점 설정 완료 (기존 방 {len(current_game_ids)}개 기록됨).")
            return

        # [사라진 방 감지 및 분류 보고]
        started_games = previous_game_ids - current_game_ids
        for g_id in started_games:
            old_game_info = previous_games[g_id]
            clean_name = old_game_info['name']
            last_slots = old_game_info['current_slots'] 
            
            if g_id in notified_milestones:
                del notified_milestones[g_id]
            
            text_time, now_obj = get_now_strings()
            
            if last_slots == 12:
                print(f"[게임 시작] {clean_name} (12/12 풀방)")
                msg = f"🎮 **[{clean_name}]** 방이 12명 풀방으로 대기를 마치고 **게임을 시작했습니다!**"
                embed = discord.Embed(description=msg, color=0x3498db)
                embed.set_footer(text=f"시작 시각: {text_time}")
                try: await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                except: pass
            else:
                print(f"[방 폭파] {clean_name} ({last_slots}명 상태에서 닫힘)")
                msg = f"💥 **[{clean_name}]** 방이 12명을 채우지 못하고 **폭파되었거나 대기실이 닫혔습니다.** ({last_slots}/12)"
                embed = discord.Embed(description=msg, color=0xe74c3c)
                embed.set_footer(text=f"폭파 시각: {text_time}")
                try: await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                except: pass

        # [새로 파진 방 및 기존 방 인원 변동 감지]
        for g_id in current_game_ids:
            game_info = current_games[g_id]
            name = game_info['name']
            current = game_info['current_slots']
            max_slots = game_info['max_slots']
            
            text_time, now_obj = get_now_strings()
            
            if g_id not in previous_game_ids:
                print(f"[새 방 생성] {name}")
                msg = f"🆕 **새 대기실 생성!**\n방 제목: {name} | 맵: {game_info['map']} | 방장: {game_info['host']} ({current}/{max_slots})"
                embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{game_info['map']}`\n• 방장: {game_info['host']} ({current}/{max_slots})", color=0x2ecc71)
                embed.set_footer(text=f"생성 시각: {text_time}")
                try: await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                except: pass
            
            # 오직 10명일 때만 알림이 가도록 수정 완료!
            if current == 10:
                if notified_milestones.get(g_id) != current:
                    notified_milestones[g_id] = current
                    print(f"[인원 달성] {name} 현재 10명!")
                    msg = f"📢 **🚀 인원 도달 알림!**\n**[{name}]** 대기실에 현재 **10명**이 모였습니다! 즉시 접속을 준비하세요! ({current}/{max_slots})"
                    embed = discord.Embed(description=msg, color=0xf1c40f)
                    embed.set_footer(text=f"감지 시각: {text_time}")
                    try: await channel.send(content=f"{msg} (확인: {text_time})", embed=embed)
                    except: pass

        previous_games = current_games
    except Exception as e:
        print(f"루프 내 에러 발생: {e}")

if __name__ == "__main__":
    flask_thread = threading.Thread(target=run_flask)
    flask_thread.daemon = True
    flask_thread.start()
    
    bot.run(TOKEN)
