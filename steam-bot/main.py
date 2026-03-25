import os
import requests
import discord

intents = discord.Intents.default()
intents.message_content = True
client = discord.Client(intents=intents)

STEAM_KEY = os.getenv('STEAM_API_KEY')
STEAM_ID = "76561199287630138"
DISCORD_TOKEN = os.getenv('DISCORD_TOKEN')

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    # --- 1. 直近2週間のプレイ時間 ---
    if message.content == '!steam':
        url = f"http://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
        response = requests.get(url).json()

        if 'response' in response and 'games' in response['response']:
            game = response['response']['games'][0]
            name = game['name']
            playtime = game.get('playtime_2weeks', 0) // 60
            await message.channel.send(f"🎮 **直近2週間**: {name} を {playtime}時間 プレイしています！")
        else:
            await message.channel.send("直近2週間で遊んだゲームが見つかりませんでした。")

    # --- 2. 全期間の総プレイ時間と内訳 ---
    elif message.content == '!steam_all':
        # include_appinfo=1 でゲーム名を取得
        url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json&include_played_free_games=1&include_appinfo=1"
        response = requests.get(url).json()

        if 'response' in response and 'games' in response['response']:
            # プレイ時間順にソート
            all_games = sorted(response['response']['games'], key=lambda x: x.get('playtime_forever', 0), reverse=True)
            
            total_hours = sum(g.get('playtime_forever', 0) for g in all_games) // 60
            
            msg = f"📊 **Steam 総プレイ時間統計**\n"
            msg += f"合計プレイ時間: **{total_hours:,} 時間**\n"
            msg += "----------------------------------\n"
            
            # 上位5件を表示（メッセージが長くなりすぎないように調整）
            for i, game in enumerate(all_games[:5], 1):
                name = game.get('name', 'Unknown')
                hours = game.get('playtime_forever', 0) // 60
                msg += f"{i}位: **{name}** ({hours:,}時間)\n"
            
            await message.channel.send(msg)
        else:
            await message.channel.send("全期間のデータが取得できませんでした。")

client.run(DISCORD_TOKEN)