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

    # --- 1. 直近2週間のプレイ時間 (アイコン付きリッチ表示) ---
    if message.content == '!steam':
        url = f"http://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
        response = requests.get(url).json()

        if 'response' in response and 'games' in response['response'] and len(response['response']['games']) > 0:
            game = response['response']['games'][0]
            name = game['name']
            appid = game['appid']
            playtime = game.get('playtime_2weeks', 0) // 60
            icon_hash = game.get('img_icon_url')

            # Embed（埋め込みメッセージ）の作成
            embed = discord.Embed(
                title="🎮 最近プレイしたゲーム",
                description=f"**{name}**",
                color=discord.Color.blue()
            )

            # アイコンURLを組み立ててセット
            if icon_hash:
                icon_url = f"http://media.steampowered.com/steamcommunity/public/images/apps/{appid}/{icon_hash}.jpg"
                embed.set_thumbnail(url=icon_url)

            embed.add_field(name="直近2週間のプレイ時間", value=f"{playtime} 時間", inline=False)
            embed.set_footer(text=f"AppID: {appid}")

            await message.channel.send(embed=embed)
        else:
            await message.channel.send("直近2週間で遊んだゲームが見つかりませんでした。")

    # --- 2. 全期間の総プレイ時間と内訳 ---
    elif message.content == '!steam_all':
        url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json&include_played_free_games=1&include_appinfo=1"
        response = requests.get(url).json()

        if 'response' in response and 'games' in response['response']:
            all_games = sorted(response['response']['games'], key=lambda x: x.get('playtime_forever', 0), reverse=True)
            total_hours = sum(g.get('playtime_forever', 0) for g in all_games) // 60
            
            msg = f"📊 **Steam 総プレイ時間統計**\n"
            msg += f"合計プレイ時間: **{total_hours:,} 時間**\n"
            msg += "----------------------------------\n"
            
            for i, game in enumerate(all_games[:5], 1):
                name = game.get('name', 'Unknown')
                hours = game.get('playtime_forever', 0) // 60
                msg += f"{i}位: **{name}** ({hours:,}時間)\n"
            
            await message.channel.send(msg)
        else:
            await message.channel.send("全期間のデータが取得できませんでした。")

    # --- 3. 全ゲームリストのファイル送信 ---
    elif message.content == '!steam_full_list':
        url = f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/?key={STEAM_KEY}&steamid={STEAM_ID}&format=json&include_played_free_games=1&include_appinfo=1"
        response = requests.get(url).json()

        if 'response' in response and 'games' in response['response']:
            all_games = sorted(response['response']['games'], key=lambda x: x.get('playtime_forever', 0), reverse=True)
            report_lines = ["=== Steam 全ゲームプレイ時間リスト ===\n"]
            for i, game in enumerate(all_games, 1):
                name = game.get('name', 'Unknown')
                hours = game.get('playtime_forever', 0) // 60
                if hours >= 0:
                    report_lines.append(f"{i:3}. {name[:40]:<40} : {hours:5,} 時間")

            full_report = "\n".join(report_lines)

            if len(full_report) > 1900:
                with open("steam_report.txt", "w", encoding="utf-8") as f:
                    f.write(full_report)
                await message.channel.send("全データの件数が多いため、ファイルにまとめました！", file=discord.File("steam_report.txt"))
                os.remove("steam_report.txt")
            else:
                await message.channel.send(f"```\n{full_report}\n```")
        else:
            await message.channel.send("データを取得できませんでした。")

client.run(DISCORD_TOKEN)