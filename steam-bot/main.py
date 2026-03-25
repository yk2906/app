import os
import requests
import discord

# 前半のIntents設定やClient作成はそのまま維持してください
# ...

STEAM_KEY = os.getenv('STEAM_API_KEY')
STEAM_ID = "76561199287630138"

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content == '!steam':  # コロンを追加
        print(f"DEBUG: Steam API Key status: {'Found' if STEAM_KEY else 'Not Found'}", flush=True)
        
        url = f"http://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
        
        # APIリクエスト実行
        response = requests.get(url).json()

        if 'response' in response and 'games' in response['response']:
            game = response['response']['games'][0]
            name = game['name']
            playtime = game.get('playtime_forever', 0) // 60
            await message.channel.send(f"直近2週間で、{name} を {playtime}時間 プレイしています！")
        else:
            await message.channel.send("最近遊んだゲームの情報が取得できませんでした。プロフィールの公開設定を確認してください。")