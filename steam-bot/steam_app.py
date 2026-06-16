import os
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
    df = pd.DataFrame(games)[["name", "playtime_forever"]]
    df["hours"] = df["playtime_forever"] // 60
    return df[df["hours"] > 0].sort_values("hours", ascending=False).reset_index(drop=True)


st.title("🎮 Steam プレイ時間ダッシュボード")

df = fetch_games()
total_hours = df["hours"].sum()
st.metric("総プレイ時間", f"{total_hours:,} 時間")

st.divider()

top_n = st.slider("上位何ゲームを表示", min_value=5, max_value=20, value=10)

top = df.head(top_n).copy()
other_hours = df.iloc[top_n:]["hours"].sum()
if other_hours > 0:
    other_row = pd.DataFrame([{"name": "その他", "hours": other_hours}])
    top = pd.concat([top, other_row], ignore_index=True)

tab1, tab2 = st.tabs(["円グラフ", "棒グラフ"])

with tab1:
    fig_pie = px.pie(top, names="name", values="hours", title=f"プレイ時間の内訳（上位{top_n}作品）")
    st.plotly_chart(fig_pie, use_container_width=True)

with tab2:
    fig_bar = px.bar(
        df.head(top_n),
        x="hours",
        y="name",
        orientation="h",
        title=f"プレイ時間ランキング（上位{top_n}作品）",
        labels={"hours": "時間", "name": "ゲーム"},
    )
    fig_bar.update_layout(yaxis={"categoryorder": "total ascending"})
    st.plotly_chart(fig_bar, use_container_width=True)

st.divider()
st.subheader("全ゲーム一覧")
st.dataframe(df.rename(columns={"name": "ゲーム名", "hours": "プレイ時間（時間）"}).drop(columns=["playtime_forever"], errors="ignore"), use_container_width=True)
