#!/usr/bin/env python3
"""Steam API の一回取得（Discord なし）。Argo Workflows / CronJob 等のバッチ用。

GetRecentlyPlayedGames の結果をログに出力するほか、GetOwnedGames から
プレイ時間の円グラフ(SVG)を生成し、GitHub Pages 用プロフィールリポジトリに
コミット・プッシュする。
"""
import json
import math
import os
import subprocess
import sys
import tempfile
import urllib.request
from xml.sax.saxutils import escape

STEAM_KEY = os.getenv("STEAM_API_KEY")
STEAM_ID = os.getenv("STEAM_ID", "76561199287630138")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
GITHUB_REPO = os.getenv("GITHUB_REPO", "yk2906/yk2906")

PIE_COLORS = [
    "#1b2838", "#66c0f4", "#a4d007", "#c2e2fa", "#417a9b",
    "#316282", "#8f98a0", "#d2e885", "#f5c518", "#e15554",
]


def _api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "steam-bot-batch/1.0"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def fetch_recently_played() -> list[dict]:
    url = (
        "https://api.steampowered.com/IPlayerService/GetRecentlyPlayedGames/v0001/"
        f"?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
    )
    return _api_get(url).get("response", {}).get("games") or []


def fetch_owned_games() -> list[dict]:
    url = (
        "https://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        f"?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
        "&include_appinfo=1&include_played_free_games=1"
    )
    return _api_get(url).get("response", {}).get("games") or []


def build_pie_svg(games: list[dict], top_n: int = 8) -> str:
    """プレイ時間上位ゲーム + その他、の円グラフをSVGで返す。"""
    played = sorted(
        (g for g in games if g.get("playtime_forever", 0) > 0),
        key=lambda g: g["playtime_forever"],
        reverse=True,
    )
    top, rest = played[:top_n], played[top_n:]

    slices = [(g.get("name", "Unknown"), g["playtime_forever"]) for g in top]
    if rest:
        slices.append(("その他", sum(g["playtime_forever"] for g in rest)))

    total = sum(value for _, value in slices)

    cx, cy, r = 150, 150, 120
    angle = -90.0
    paths = []
    legend_items = []
    for i, (name, minutes) in enumerate(slices):
        sweep = (minutes / total) * 360
        x1 = cx + r * math.cos(math.radians(angle))
        y1 = cy + r * math.sin(math.radians(angle))
        angle2 = angle + sweep
        x2 = cx + r * math.cos(math.radians(angle2))
        y2 = cy + r * math.sin(math.radians(angle2))
        large_arc = 1 if sweep > 180 else 0
        color = PIE_COLORS[i % len(PIE_COLORS)]

        paths.append(
            f'<path d="M{cx},{cy} L{x1:.2f},{y1:.2f} '
            f'A{r},{r} 0 {large_arc} 1 {x2:.2f},{y2:.2f} Z" fill="{color}"/>'
        )

        legend_y = 20 + i * 22
        hours = minutes / 60
        legend_items.append(
            f'<rect x="320" y="{legend_y}" width="14" height="14" fill="{color}"/>'
            f'<text x="340" y="{legend_y + 12}" font-size="13" '
            f'font-family="sans-serif">{escape(name)} ({hours:,.1f}h)</text>'
        )

        angle = angle2

    return (
        '<svg xmlns="http://www.w3.org/2000/svg" width="600" height="320" '
        'viewBox="0 0 600 320">'
        '<rect width="600" height="320" fill="#ffffff"/>'
        '<text x="150" y="20" font-size="16" font-family="sans-serif" '
        'text-anchor="middle" font-weight="bold">Steam プレイ時間</text>'
        f'<g transform="translate(0,10)">{"".join(paths)}</g>'
        f'{"".join(legend_items)}'
        "</svg>"
    )


def push_chart_to_github(svg: str) -> None:
    if not GITHUB_TOKEN:
        print("GITHUB_TOKEN is not set; skip pushing chart", file=sys.stderr)
        return

    repo_url = f"https://x-access-token:{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"

    with tempfile.TemporaryDirectory() as tmpdir:
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", repo_url, tmpdir],
                check=True, capture_output=True, text=True,
            )

            asset_path = os.path.join(tmpdir, "assets", "steam-playtime.svg")
            os.makedirs(os.path.dirname(asset_path), exist_ok=True)
            with open(asset_path, "w", encoding="utf-8") as f:
                f.write(svg)

            subprocess.run(["git", "-C", tmpdir, "config", "user.name", "steam-bot"], check=True)
            subprocess.run(
                ["git", "-C", tmpdir, "config", "user.email", "steam-bot@users.noreply.github.com"],
                check=True,
            )
            subprocess.run(["git", "-C", tmpdir, "add", "assets/steam-playtime.svg"], check=True)

            if subprocess.run(["git", "-C", tmpdir, "diff", "--cached", "--quiet"]).returncode == 0:
                print("Steamプレイ時間チャートに変更なし")
                return

            subprocess.run(
                ["git", "-C", tmpdir, "commit", "-m", "main [chore] Steamプレイ時間チャートを更新"],
                check=True, capture_output=True, text=True,
            )
            subprocess.run(
                ["git", "-C", tmpdir, "push"],
                check=True, capture_output=True, text=True,
            )
            print("Steamプレイ時間チャートを更新しました")
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git operation failed (exit={e.returncode})") from None


def main() -> int:
    if not STEAM_KEY:
        print("STEAM_API_KEY is not set", file=sys.stderr)
        return 1

    recent = fetch_recently_played()
    print(f"steamid={STEAM_ID} recently_played_count={len(recent)}")
    for g in recent[:10]:
        name = g.get("name", "?")
        h2 = (g.get("playtime_2weeks", 0) or 0) // 60
        print(f"  - {name} (2週間: {h2}h)")

    owned = fetch_owned_games()
    if not owned:
        print("所持ゲームが見つかりませんでした", file=sys.stderr)
        return 1

    svg = build_pie_svg(owned)
    push_chart_to_github(svg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
