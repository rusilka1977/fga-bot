import os
import discord
from discord.ext import tasks, commands
import requests

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------- [개인 설정] -----------------
TOKEN = "os.getenv("TOKEN")"
CHANNEL_ID = 1521217489134948433
SEARCH_KEYWORD = "fatega"  
# ----------------------------------------------

previous_games = {} 
is_first_run = True

@bot.event
async def on_ready():
    print(f"{bot.user.name} 봇이 성공적으로 로그인했습니다!")
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        try:
            embed = discord.Embed(
                title="🤖 워크래프트 3 모니터링 시작",
                description=f"FGA bot이 가동되었습니다.\n시작/방폭 구별 모드가 적용되었습니다!",
                color=0x3498db
            )
            await channel.send(embed=embed)
        except Exception as e:
            print(f"로그인 인사말 디코 발송 실패: {e}")
    monitor_gamelist.start()

@tasks.loop(seconds=5)
async def monitor_gamelist():
    global previous_games, is_first_run
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
            
            # Case 1: 12명 풀방으로 완벽하게 사라진 경우 -> 게임 시작 판정
            if last_slots == 12:
                print(f"[게임 시작] {clean_name} (12/12 풀방)")
                msg = f"🎮 **[{clean_name}]** 방이 12명 풀방으로 대기를 마치고 **게임을 시작했습니다!**"
                embed = discord.Embed(description=msg, color=0x3498db) # 시작은 파란색 박스
                try:
                    await channel.send(content=msg, embed=embed)
                except:
                    pass
            
            # Case 2: 12명이 채워지지 않은 상태로 사라진 경우 -> 방폭 판정
            else:
                print(f"[방 폭파] {clean_name} ({last_slots}명 상태에서 닫힘)")
                msg = f"💥 **[{clean_name}]** 방이 12명을 채우지 못하고 **폭파되었거나 대기실이 닫혔습니다.** ({last_slots}/12)"
                embed = discord.Embed(description=msg, color=0xe74c3c) # 방폭은 빨간색 박스
                try:
                    await channel.send(content=msg, embed=embed)
                except:
                    pass

        # [새로 파진 방 감지]
        new_games = current_game_ids - previous_game_ids
        for g_id in new_games:
            game_info = current_games[g_id]
            name = game_info['name']
            map_name = game_info['map']
            host = game_info['host']
            current = game_info['current_slots']
            max_slots = game_info['max_slots']
            print(f"[새 방 생성] {name}")
            msg = f"🆕 **새 대기실 생성!**\n방 제목: {name} | 맵: {map_name} | 방장: {host} ({current}/{max_slots})"
            embed = discord.Embed(title="🆕 새 대기실 생성!", description=f"**방 제목:** {name}\n• 맵: `{map_name}`\n• 방장: {host} ({current}/{max_slots})", color=0x2ecc71)
            try:
                await channel.send(content=msg, embed=embed)
            except:
                pass

        previous_games = current_games
    except Exception as e:
        print(f"루프 내 에러 발생: {e}")

bot.run(TOKEN)
