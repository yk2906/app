"""
Slack の会話／チャンネルから最新テキスト 1 件を Notion ページへ引用で追記する。

環境変数（.env）
  SLACK_BOT_TOKEN または SLACK_USER_TOKEN
  MY_DM_CHANNEL_ID（優先）または SLACK_USER_ID
  NOTION_TOKEN / NOTION_PAGE_ID（インテグレーションをページに接続すること）
  SLACK_DEBUG=1 … 任意。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from notion_client import Client
from notion_client.errors import APIErrorCode, APIResponseError
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

# -----------------------------------------------------------------------------
# 定数・起動設定
# -----------------------------------------------------------------------------

_NOTION_PLAIN_TEXT_MAX = 2000
_SLACK_HISTORY_PAGE_SIZE = 50
_THREAD_REPLIES_MAX = 200
_DEBUG_TAIL_MESSAGES = 5

load_dotenv(Path(__file__).resolve().parent / ".env")


def _env(key: str) -> str | None:
    v = os.environ.get(key)
    return v.strip() if v else None


def _slack_token() -> str | None:
    return _env("SLACK_BOT_TOKEN") or _env("SLACK_USER_TOKEN")


slack_client = WebClient(token=_slack_token())
notion_client = Client(auth=_env("NOTION_TOKEN"))


# -----------------------------------------------------------------------------
# Slack: 共通ユーティリティ
# -----------------------------------------------------------------------------


def _as_text(val: object) -> str:
    """Slack API が返す text 相当を正規化した str にする。"""
    if val is None:
        return ""
    if isinstance(val, str):
        return val.strip()
    if isinstance(val, (list, dict)):
        try:
            return json.dumps(val, ensure_ascii=False).strip()
        except (TypeError, ValueError):
            return ""
    return str(val).strip()


def _slack_block_kit_text(blob: object) -> str:
    """Block Kit の text / プレーンテキスト用オブジェクトから本文のみ取得。"""
    if isinstance(blob, dict):
        return _as_text(blob.get("text"))
    return _as_text(blob)


def _slack_err_meta(exc: SlackApiError) -> tuple[str | None, object]:
    resp = exc.response
    code = resp.get("error") if resp else None
    return code, getattr(resp, "data", resp)


def _slack_scope_hint(exc: SlackApiError) -> str:
    _, data = _slack_err_meta(exc)
    if not isinstance(data, dict):
        return ""
    lines: list[str] = []
    if need := data.get("needed"):
        lines.append(f"Slack が要求しているスコープ: {need}")
        lines.append("Bot Token Scopes に不足分を追加（channels:history 等、会話種別により異なる）。")
    if prov := data.get("provided"):
        lines.append(f"現在のスコープ: {prov}")
    return "\n".join(lines)


def _abort_slack_missing_scope(exc: SlackApiError, headline: str, *, history: bool) -> None:
    """missing_scope のときのみ SystemExit。それ以外は例外をそのまま再送出。"""
    code, detail = _slack_err_meta(exc)
    if code != "missing_scope":
        raise exc
    if history:
        hint = _slack_scope_hint(exc)
        tail = (hint + "\n\n" if hint else "") + (
            "手順: Bot スコープ追加 → ワークスペースへ再インストール → 新トークンを .env へ。\n\n"
            f"Slack の応答: {detail}"
        )
        raise SystemExit(f"{headline}\n\n{tail}") from exc
    raise SystemExit(
        f"{headline}\nBot に im:write を追加し再インストール後、トークンを更新してください。\n\n"
        f"詳細: {detail}"
    ) from exc


# -----------------------------------------------------------------------------
# Slack: メッセージ本文の抽出（Block Kit 等）
# -----------------------------------------------------------------------------


def _extract_rich_element(el: dict[str, Any]) -> str:
    t = el.get("type")
    if t in ("rich_text_section", "rich_text_quote"):
        return "".join(
            _extract_rich_element(c) for c in el.get("elements") or [] if isinstance(c, dict)
        )
    if t == "rich_text_list":
        return "\n".join(
            _extract_rich_element(c) for c in el.get("elements") or [] if isinstance(c, dict)
        )
    if t == "rich_text_preformatted":
        x = el.get("text")
        return x if isinstance(x, str) else ""
    if t == "text":
        return str(el.get("text") or "")
    if t == "emoji" and el.get("name"):
        return f":{el['name']}:"
    return ""


def _extract_from_block(block: dict[str, Any]) -> str:
    bt = block.get("type")

    if bt in ("section", "header"):
        parts: list[str] = []
        if p := _slack_block_kit_text(block.get("text")):
            parts.append(p)
        if bt == "section":
            for f in block.get("fields") or []:
                if isinstance(f, dict) and (line := _slack_block_kit_text(f)):
                    parts.append(line)
        return "\n".join(parts).strip()

    if bt == "actions":
        labels = [
            _slack_block_kit_text(el.get("text"))
            for el in block.get("elements") or []
            if isinstance(el, dict) and el.get("type") == "button"
        ]
        return " ".join(x for x in labels if x).strip()

    if bt == "image":
        return (block.get("alt_text") or "").strip() or _slack_block_kit_text(block.get("title"))

    if bt == "context":
        return " ".join(
            (el.get("text") or "").strip()
            for el in block.get("elements") or []
            if isinstance(el, dict) and el.get("type") == "mrkdwn" and (el.get("text") or "").strip()
        )

    if bt == "rich_text":
        chunks: list[str] = []
        for el in block.get("elements") or []:
            if isinstance(el, dict) and (c := _extract_rich_element(el)):
                chunks.append(c)
        return "\n".join(chunks)

    return ""


def _message_plain(msg: dict[str, Any]) -> str:
    """単一 Slack message オブジェクトから Notion に載せるプレーン文言を組み立てる。"""
    if t := _as_text(msg.get("text")):
        return t
    for att in msg.get("attachments") or []:
        if not isinstance(att, dict):
            continue
        for key in ("pretext", "text", "fallback", "title"):
            if v := _as_text(att.get(key)):
                return v

    blocks = msg.get("blocks")
    if isinstance(blocks, list):
        lines = [ln for b in blocks if isinstance(b, dict) and (ln := _extract_from_block(b))]
        if lines:
            return "\n".join(lines).strip()

    labels: list[str] = []
    for f in msg.get("files") or []:
        if not isinstance(f, dict):
            continue
        lbl = _as_text(f.get("title")) or _as_text(f.get("name")) or _as_text(f.get("mimetype"))
        if lbl:
            labels.append(lbl)
    if labels:
        return "[ファイル] " + "\n".join(labels)
    return ""


def _slack_message_ts_seconds(msg: dict[str, Any]) -> float | None:
    ts = msg.get("ts")
    if ts is None:
        return None
    try:
        return float(ts)
    except (TypeError, ValueError):
        return None


def _debug_print_recent_messages(channel_id: str, messages: list[Any]) -> None:
    print(f"[slack debug] channel={channel_id!r} count={len(messages)} limit={_SLACK_HISTORY_PAGE_SIZE}")
    tail = messages[-_DEBUG_TAIL_MESSAGES:] if len(messages) > _DEBUG_TAIL_MESSAGES else messages
    for m in reversed(tail):
        if not isinstance(m, dict):
            continue
        print(
            "[slack debug] ts=%s user=%s subtype=%s text_len=%i blocks=%s files=%s reply=%s"
            % (
                m.get("ts"),
                m.get("user"),
                m.get("subtype"),
                len(_as_text(m.get("text"))),
                bool(m.get("blocks")),
                len(m.get("files") or []),
                m.get("reply_count"),
            )
        )


def _collect_parent_message_candidates(messages: list[Any]) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    for mm in messages:
        if not isinstance(mm, dict):
            continue
        ts = _slack_message_ts_seconds(mm)
        if ts is None:
            continue
        if txt := _message_plain(mm):
            out.append((ts, txt))
    return out


def _collect_thread_reply_candidates(channel_id: str, messages: list[Any]) -> list[tuple[float, str]]:
    """各親のスレッド返信から (unix秒風タイムスタンプ, 本文) を集める。"""
    out: list[tuple[float, str]] = []
    for mm in messages:
        if not isinstance(mm, dict):
            continue
        ts_raw = mm.get("ts")
        reply_count = int(mm.get("reply_count") or 0)
        if reply_count <= 0 or ts_raw is None:
            continue
        try:
            rep = slack_client.conversations_replies(
                channel=channel_id,
                ts=str(ts_raw),
                limit=min(_THREAD_REPLIES_MAX, max(reply_count + 5, 20)),
            )
        except SlackApiError:
            continue

        for rm in rep.get("messages") or []:
            if not isinstance(rm, dict) or rm.get("ts") == ts_raw:
                continue
            rts = _slack_message_ts_seconds(rm)
            if rts is None:
                continue
            if txt := _message_plain(rm):
                out.append((rts, txt))
    return out


def fetch_latest_slack_text(channel_id: str) -> tuple[str | None, int]:
    """
    Slack の親メッセージとそのスレッド返信から、タイムスタンプが最も新しい本文を 1 件選ぶ。

    Returns:
        (本文, 親メッセージ件数)。抽出できなければ (None, 親件数)。
    """
    try:
        hist = slack_client.conversations_history(channel=channel_id, limit=_SLACK_HISTORY_PAGE_SIZE)
    except SlackApiError as e:
        code, detail = _slack_err_meta(e)
        if code == "missing_scope":
            _abort_slack_missing_scope(
                e,
                "Slack API: conversations.history が missing_scope です。",
                history=True,
            )
        if code == "channel_not_found":
            raise SystemExit(
                "channel_not_found: Bot がこの会話に参加していない／ID が無効です。\n\n"
                f"Slack: {detail}"
            ) from e
        raise

    messages: list[Any] = hist.get("messages") or []
    parent_count = len(messages)

    if _env("SLACK_DEBUG"):
        _debug_print_recent_messages(channel_id, messages)

    if not messages:
        return None, 0

    candidates = _collect_parent_message_candidates(messages)
    candidates.extend(_collect_thread_reply_candidates(channel_id, messages))

    if not candidates:
        return None, parent_count
    candidates.sort(key=lambda x: x[0])
    return candidates[-1][1], parent_count


def resolve_channel_id() -> str:
    """MY_DM_CHANNEL_ID があればそれを優先し、無ければ SLACK_USER_ID で DM を開く。"""
    if cid := _env("MY_DM_CHANNEL_ID"):
        if _env("SLACK_USER_ID"):
            print("[Slack] MY_DM_CHANNEL_ID を使用（SLACK_USER_ID は未使用）。")
        return cid

    uid = _env("SLACK_USER_ID")
    if not uid:
        raise SystemExit("MY_DM_CHANNEL_ID または SLACK_USER_ID を .env に設定してください。")

    try:
        opened = slack_client.conversations_open(users=uid)
    except SlackApiError as e:
        _abort_slack_missing_scope(e, "conversations.open が missing_scope です。", history=False)

    if not opened.get("ok"):
        raise SystemExit(f"conversations.open 失敗: {opened}")
    cid = opened.get("channel", {}).get("id")
    if not cid:
        raise SystemExit(f"conversations.open に channel.id がありません: {opened}")
    return str(cid)


def diagnose_empty_channel(channel_id: str) -> None:
    """履歴 0 件時のワークスペース／会話メタのみ表示（デバッグ用）。"""
    try:
        at = slack_client.auth_test()
        print(f"[Slack] auth_test team={at.get('team')!r} user_id={at.get('user_id')!r}")
    except SlackApiError as e:
        print("[Slack] auth_test:", _slack_err_meta(e)[1])
        return

    try:
        info = slack_client.conversations_info(channel=channel_id).get("channel") or {}
    except SlackApiError as e:
        code, payload = _slack_err_meta(e)
        print("[Slack] conversations.info:", payload)
        if code == "missing_scope":
            print("ヒント: 診断用に im:read を Bot に付けると info が通ります。")
        return

    print(
        f"[Slack] conversations.info is_im={info.get('is_im')} "
        f"mpim={info.get('is_mpim')} archived={info.get('is_archived')} "
        f"peer_user={info.get('user')!r}"
    )
    env_u, peer = _env("SLACK_USER_ID"), info.get("user")
    if isinstance(env_u, str) and peer and peer != env_u:
        print("ヒント: SLACK_USER_ID と DM 相手 user が一致していません。")


# -----------------------------------------------------------------------------
# Notion
# -----------------------------------------------------------------------------


def notion_plain(raw: object) -> str:
    """Notion `rich_text` の content に入れるプレーン文字列へ。"""
    s = raw.strip() if isinstance(raw, str) else _as_text(raw)
    s = s.replace("\x00", "")
    if len(s) > _NOTION_PLAIN_TEXT_MAX:
        s = s[: _NOTION_PLAIN_TEXT_MAX - 1] + "…"
    return s


def _quote_child_block(plain: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "quote",
        "quote": {"rich_text": [{"type": "text", "text": {"content": plain}}]},
    }


def append_quote_to_page(page_id: str, plain: str) -> None:
    if not plain:
        raise ValueError("貼り付ける文字列が空です。")
    try:
        notion_client.blocks.children.append(block_id=page_id, children=[_quote_child_block(plain)])
    except APIResponseError as e:
        detail = str(e).strip()
        if e.code == APIErrorCode.ObjectNotFound:
            raise SystemExit(
                "Notion: ページが見つからない／インテグレーションに接続していません。\n"
                "ページの⋯→接続でトークンのインテグレーションを追加。NOTION_PAGE_ID は URL の p=。\n\n"
                f"{detail}"
            ) from e
        if e.code == APIErrorCode.RestrictedResource:
            raise SystemExit(f"Notion: 権限不足（restricted_resource）。\n{detail}") from e
        raise


# -----------------------------------------------------------------------------
# エントリポイント
# -----------------------------------------------------------------------------


def _ensure_slack_configured() -> None:
    token = _slack_token()
    if not token:
        raise SystemExit("SLACK_BOT_TOKEN または SLACK_USER_TOKEN が未設定です。")
    if not token.startswith("xox"):
        raise SystemExit("Slack OAuth トークン（xox…）を .env に設定してください。")


def _ensure_notion_configured() -> str:
    if not _env("NOTION_TOKEN"):
        raise SystemExit("NOTION_TOKEN が未設定です。")
    page_id = _env("NOTION_PAGE_ID")
    if not page_id:
        raise SystemExit("NOTION_PAGE_ID が未設定です。")
    return page_id


def main() -> None:
    _ensure_slack_configured()

    channel_id = resolve_channel_id()
    slack_text, parent_count = fetch_latest_slack_text(channel_id)

    if not slack_text:
        print("転記できるテキストがありませんでした。")
        print(f"[Slack] 親メッセージ件数={parent_count} channel={channel_id!r}")
        if parent_count == 0:
            print("履歴なし・未参加会話・未送信等を確認。MY_DM_CHANNEL_ID が意図どおりかも。")
            diagnose_empty_channel(channel_id)
        else:
            print("text/ブロックから抽出不可。files:read や SLACK_DEBUG=1 を確認。")
        raise SystemExit(0)

    page_id = _ensure_notion_configured()

    normalized = notion_plain(slack_text)
    if not normalized:
        raise SystemExit("正規化後に空です。SLACK_DEBUG=1 で切り分けてください。")

    append_quote_to_page(page_id, normalized)
    print("Notion に追記しました。")


if __name__ == "__main__":
    main()
