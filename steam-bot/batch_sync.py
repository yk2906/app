#!/usr/bin/env python3
"""Steam API の一回取得（Discord なし）。Argo Workflows / CronJob 等のバッチ用。"""
import json
import os
import sys
import urllib.request

STEAM_KEY = os.getenv("STEAM_API_KEY")
STEAM_ID = os.getenv("STEAM_ID", "76561199287630138")


def main() -> int:
    if not STEAM_KEY:
        print("STEAM_API_KEY is not set", file=sys.stderr)
        return 1

    url = (
        "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/"
        f"?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "steam-bot-batch/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = json.loads(resp.read().decode())

    games = body.get("response", {}).get("games") or []
    print(f"steamid={STEAM_ID} recently_played_count={len(games)}")
    for g in games[:10]:
        name = g.get("name", "?")
        h2 = (g.get("playtime_2weeks", 0) or 0) // 60
        print(f"  - {name} (2週間: {h2}h)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
