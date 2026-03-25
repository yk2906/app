import os
import requests
import discord

STEAM_KEY = os.getenv('STEAM_API_KEY')
STEAM_ID = "76561199287630138"

@client.event
async def on_message(message):
    if message.author == client.user:
        return

    if message.content == '!steam'
        url = url = f"http://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
        response = requests.get(url).json()

        if 'games' in response['response']:
            game = response['response']['games'][0]
            name = game['name']
            playtime = game['playtime_forever'] // 60
            await message.channel.send(f"直近2週間で、{name} を {playtime}時間 プレイしています！")
        else:
            await message.channel.send("最近遊んだゲームが見つかりませんでした。")