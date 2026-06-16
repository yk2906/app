import os
import time
import requests
import pandas as pd
import plotly.express as px
import streamlit as st

STEAM_KEY = os.getenv("STEAM_API_KEY")
STEAM_ID = "76561199287630138"


@st.cache_data
def fetch_games():
    if not STEAM_KEY:
        st.error("STEAM_API_KEY が設定されていません。Streamlit Cloud の Secrets を確認してください。")
        st.stop()
    url = (
        f"http://api.steampowered.com/IPlayerService/GetOwnedGames/v0001/"
        f"?key={STEAM_KEY}&steamid={STEAM_ID}&format=json"
        f"&include_played_free_games=1&include_appinfo=1"
    )
    res = requests.get(url, timeout=30).json()
    if "response" not in res or "games" not in res.get("response", {}):
        st.error(f"Steam API からデータを取得できませんでした。APIキーやSteam IDを確認してください。\nレスポンス: {res}")
        st.stop()
    games = res["response"]["games"]
    df = pd.DataFrame(games)[["appid", "name", "playtime_forever"]]
    df["hours"] = df["playtime_forever"] // 60
    return df.sort_values("hours", ascending=False).reset_index(drop=True)


@st.cache_data
def fetch_achievement_rates(appids_and_names: list[tuple]) -> pd.DataFrame:
    rows = []
    for appid, name in appids_and_names:
        url = (
            f"http://api.steampowered.com/ISteamUserStats/GetPlayerAchievements/v0001/"
            f"?key={STEAM_KEY}&steamid={STEAM_ID}&appid={appid}&format=json"
        )
        try:
            res = requests.get(url, timeout=10).json()
            achievements = res.get("playerstats", {}).get("achievements", [])
            if not achievements:
                continue
            total = len(achievements)
            unlocked = sum(1 for a in achievements if a.get("achieved") == 1)
            rows.append({"name": name, "unlocked": unlocked, "total": total, "rate": unlocked / total * 100})
        except Exception:
            continue
        time.sleep(0.3)
    return pd.DataFrame(rows).sort_values("rate", ascending=False).reset_index(drop=True)


@st.cache_data
def fetch_genres(appids_and_names: list[tuple]) -> pd.DataFrame:
    genre_counts: dict[str, int] = {}
    for appid, _ in appids_and_names:
        url = f"https://store.steampowered.com/api/appdetails?appids={appid}&filters=genres&l=japanese"
        try:
            res = requests.get(url, timeout=10).json()
            genres = res.get(str(appid), {}).get("data", {}).get("genres", [])
            for g in genres:
                label = g.get("description", "不明")
                genre_counts[label] = genre_counts.get(label, 0) + 1
        except Exception:
            continue
        time.sleep(0.3)
    df = pd.DataFrame(genre_counts.items(), columns=["genre", "count"])
    return df.sort_values("count", ascending=False).reset_index(drop=True)


# ----------------------------------------------------------------
st.title("🎮 Steam プレイ時間ダッシュボード")

df = fetch_games()
played_df = df[df["hours"] > 0]
total_hours = played_df["hours"].sum()

st.metric("総プレイ時間", f"{total_hours:,} 時間")
st.divider()

# --- プレイ時間セクション ---
top_n = st.slider("上位何ゲームを表示", min_value=5, max_value=20, value=10)

top = played_df.head(top_n).copy()
other_hours = played_df.iloc[top_n:]["hours"].sum()
if other_hours > 0:
    top = pd.concat([top, pd.DataFrame([{"name": "その他", "hours": other_hours}])], ignore_index=True)

tab1, tab2 = st.tabs(["円グラフ", "棒グラフ"])

with tab1:
    top_sorted = top.sort_values("hours", ascending=False)
    fig_pie = px.pie(top_sorted, names="name", values="hours", title=f"プレイ時間の内訳（上位{top_n}作品）")
    fig_pie.update_traces(direction="clockwise", sort=False)
    st.plotly_chart(fig_pie, use_container_width=True)

with tab2:
    fig_bar = px.bar(
        played_df.head(top_n),
        x="hours",
        y="name",
        orientation="h",
        title=f"プレイ時間ランキング（上位{top_n}作品）",
        labels={"hours": "時間", "name": "ゲーム"},
    )
    fig_bar.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig_bar, use_container_width=True)

st.divider()

# --- 実績達成率セクション ---
st.subheader("🏆 実績達成率ランキング")
ach_n = st.slider("対象ゲーム数（プレイ時間上位）", min_value=5, max_value=20, value=10, key="ach_slider")

with st.spinner("実績データを取得中..."):
    target = list(played_df.head(ach_n)[["appid", "name"]].itertuples(index=False, name=None))
    ach_df = fetch_achievement_rates(target)

if ach_df.empty:
    st.info("実績データを取得できませんでした。")
else:
    fig_ach = px.bar(
        ach_df,
        x="rate",
        y="name",
        orientation="h",
        title="実績達成率（%）",
        labels={"rate": "達成率 (%)", "name": "ゲーム"},
        text=ach_df.apply(lambda r: f"{r['unlocked']}/{r['total']}", axis=1),
    )
    fig_ach.update_layout(yaxis={"categoryorder": "total ascending"}, xaxis_range=[0, 100])
    st.plotly_chart(fig_ach, use_container_width=True)

st.divider()

# --- ジャンル分布セクション ---
st.subheader("🎯 ゲームジャンル分布")
genre_n = st.slider("対象ゲーム数（プレイ時間上位）", min_value=10, max_value=30, value=20, key="genre_slider")

with st.spinner("ジャンルデータを取得中..."):
    genre_target = list(played_df.head(genre_n)[["appid", "name"]].itertuples(index=False, name=None))
    genre_df = fetch_genres(genre_target)

if genre_df.empty:
    st.info("ジャンルデータを取得できませんでした。")
else:
    fig_genre = px.pie(genre_df, names="genre", values="count", title=f"ジャンル分布（上位{genre_n}作品）")
    fig_genre.update_traces(direction="clockwise", sort=False)
    st.plotly_chart(fig_genre, use_container_width=True)

st.divider()
st.subheader("全ゲーム一覧")
st.dataframe(
    df.rename(columns={"name": "ゲーム名", "hours": "プレイ時間（時間）"})
      .drop(columns=["playtime_forever", "appid"], errors="ignore"),
    use_container_width=True,
)
