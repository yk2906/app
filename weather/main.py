#!/usr/bin/env python3
"""Open-Meteo API から明日の天気予報を取得する。"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# WMO Weather interpretation codes (Open-Meteo)
WEATHER_LABELS: dict[int, str] = {
    0: "快晴",
    1: "晴れ",
    2: "一部曇り",
    3: "曇り",
    45: "霧",
    48: "着氷性の霧",
    51: "弱い霧雨",
    53: "霧雨",
    55: "強い霧雨",
    56: "着氷性の弱い霧雨",
    57: "着氷性の霧雨",
    61: "弱い雨",
    63: "雨",
    65: "強い雨",
    66: "着氷性の弱い雨",
    67: "着氷性の雨",
    71: "弱い雪",
    73: "雪",
    75: "強い雪",
    77: "霧雪",
    80: "にわか雨",
    81: "にわか雨",
    82: "激しいにわか雨",
    85: "にわか雪",
    86: "激しいにわか雪",
    95: "雷雨",
    96: "雹を伴う雷雨",
    99: "激しい雹を伴う雷雨",
}


@dataclass(frozen=True)
class TomorrowForecast:
    date: str
    weather: str
    temp_max_c: float
    temp_min_c: float
    precipitation_mm: float
    precipitation_probability_pct: int | None

    def format(self) -> str:
        lines = [
            f"日付: {self.date}",
            f"天気: {self.weather}",
            f"最高気温: {self.temp_max_c:.1f}°C",
            f"最低気温: {self.temp_min_c:.1f}°C",
            f"降水量: {self.precipitation_mm:.1f} mm",
        ]
        if self.precipitation_probability_pct is not None:
            lines.append(f"降水確率: {self.precipitation_probability_pct}%")
        return "\n".join(lines)

    def format_discord(self) -> str:
        lines = [
            "🌤️ **明日の天気予報**",
            f"**日付:** {self.date}",
            f"**天気:** {self.weather}",
            f"**最高気温:** {self.temp_max_c:.1f}°C",
            f"**最低気温:** {self.temp_min_c:.1f}°C",
            f"**降水量:** {self.precipitation_mm:.1f} mm",
        ]
        if self.precipitation_probability_pct is not None:
            lines.append(f"**降水確率:** {self.precipitation_probability_pct}%")
        return "\n".join(lines)


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    return float(raw)


def _tomorrow_date(timezone: str) -> str:
    tz = ZoneInfo(timezone)
    return (datetime.now(tz).date() + timedelta(days=1)).isoformat()


def _weather_label(code: int) -> str:
    return WEATHER_LABELS.get(code, f"不明 (code={code})")


def fetch_tomorrow_forecast(
    latitude: float,
    longitude: float,
    timezone: str = "Asia/Tokyo",
    timeout: float = 30.0,
) -> TomorrowForecast:
    params = urllib.parse.urlencode(
        {
            "latitude": latitude,
            "longitude": longitude,
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "precipitation_sum,precipitation_probability_max"
            ),
            "timezone": timezone,
            "forecast_days": 2,
        }
    )
    url = f"{OPEN_METEO_URL}?{params}"
    req = urllib.request.Request(url, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"Open-Meteo API failed: {e.code} {e.reason}") from e
    except OSError as e:
        raise SystemExit(f"Open-Meteo API failed: {e}") from e

    daily = payload.get("daily")
    if not daily or not daily.get("time"):
        raise SystemExit("Open-Meteo API returned no daily forecast")

    target = _tomorrow_date(timezone)
    try:
        idx = daily["time"].index(target)
    except ValueError as e:
        raise SystemExit(
            f"Tomorrow ({target}) not found in forecast: {daily['time']}"
        ) from e

    precip_prob = daily.get("precipitation_probability_max")
    return TomorrowForecast(
        date=target,
        weather=_weather_label(int(daily["weather_code"][idx])),
        temp_max_c=float(daily["temperature_2m_max"][idx]),
        temp_min_c=float(daily["temperature_2m_min"][idx]),
        precipitation_mm=float(daily["precipitation_sum"][idx]),
        precipitation_probability_pct=(
            int(precip_prob[idx]) if precip_prob is not None else None
        ),
    )


def _env_optional(name: str) -> str | None:
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return None
    return raw.strip()


def send_discord_message(content: str, timeout: float = 30.0) -> None:
    token = _env_optional("DISCORD_TOKEN")
    channel_id = _env_optional("DISCORD_CHANNEL_ID")

    if token is None and channel_id is None:
        return
    if token is None or channel_id is None:
        raise SystemExit(
            "DISCORD_TOKEN and DISCORD_CHANNEL_ID must both be set for Discord notify"
        )

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = json.dumps({"content": content}).encode()
    req = urllib.request.Request(
        url,
        data=payload,
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "User-Agent": "weather-bot/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            resp.read()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise SystemExit(f"Discord API failed: {e.code} {e.reason}: {body}") from e
    except OSError as e:
        raise SystemExit(f"Discord API failed: {e}") from e


def main() -> None:
    latitude = _env_float("LATITUDE", 35.6762)  # 東京
    longitude = _env_float("LONGITUDE", 139.6503)
    timezone = os.environ.get("TIMEZONE", "Asia/Tokyo").strip() or "Asia/Tokyo"
    timeout = _env_float("HTTP_GET_TIMEOUT", 30.0)

    forecast = fetch_tomorrow_forecast(
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        timeout=timeout,
    )
    text = forecast.format()
    print(text)
    send_discord_message(forecast.format_discord(), timeout=timeout)


if __name__ == "__main__":
    main()
