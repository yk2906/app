import discord
import os

# 接続に必要な「インテント」の設定
intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

@client.event
async def on_ready():
    print(f'--- Logged in as {client.user} (ID: {client.user.id}) ---', flush=True)

@client.event
async def on_message(message):
    # 自分のメッセージには反応しない
    if message.author == client.user:
        return

    if message.content == '!hello':
        await message.channel.send('Hello from OCI (k3s)!')

# 本番では環境変数から読み込むようにします
TOKEN = os.getenv('DISCORD_TOKEN')
client.run(TOKEN)