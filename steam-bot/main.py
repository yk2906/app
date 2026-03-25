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
    print(f"DEBUG: 受信メッセージ内容: '{message.content}'", flush=True)
    if message.author == client.user:
        return

    if message.content == '!steam_all':
        print("DEBUG: 全ゲームの総プレイ時間を計算中...", flush=True)
        
        # 全所有ゲームを取得するAPI
        url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json&include_played_free_games=1"
        
        response = requests.get(url).json()

        if 'response' in response and 'games' in response['response']:
            games = response['response']['games']
            
            # 全てのゲームの playtime_forever を合計する
            total_minutes = sum(game.get('playtime_forever', 0) for game in games)
            total_hours = total_minutes // 60
            game_count = len(games)
            
            # ついでに一番遊んでいるゲームを探す
            top_game = max(games, key=lambda x: x.get('playtime_forever', 0))
            top_game_name = "不明（API設定により取得不可）" 
            # ※ゲーム名を取得するには追加のパラメータ '&include_appinfo=1' が必要です
            
            await message.channel.send(
                f"📊 **Steam統計データ**\n"
                f"・所有ゲーム数: {game_count} タイトル\n"
                f"・総プレイ時間: **{total_hours:,} 時間**\n"
                f"（一生のうち、約 {total_hours // 24} 日間をSteamに捧げています！）"
            )
        else:
            await message.channel.send("ゲーム一覧が取得できませんでした。プロフィールの「ゲームの詳細」が公開になっているか再確認してください。")

client.run(DISCORD_TOKEN)