# report-bot

月次レポート（Udemy受講レポート x2、自主勉強会開催レポート）の完成チェックとメール提出をSlackから行うためのGo製サーバーです。

## できること

- Slackの Slash Command（`/check-reports`）から、Google Sheetsを参照して3レポートの完成状況を判定
- 未完成の項目があれば、レポートごとに不足項目をSlackへ通知
- 全て完成していれば、宛先・件名・本文・添付ファイル名を表示し「送信」ボタン付きのメッセージを投稿
- ボタン押下（Interactivity）で、Google Driveから該当ファイルをxlsxとしてエクスポートし、SMTP経由で添付ファイル付きメールを送信
- 送信結果をSlackメッセージに反映

`infra`リポジトリの`kubernetes/report-bot/`にデプロイ定義があり、GitHub Actions（`.github/workflows/report-bot.yaml`）でビルド・GHCRへのpush・`infra`のイメージタグ自動更新までを行います。ArgoCDが同期し、Cloudflare Tunnel（`cloudflared`）経由で`https://report-bot.mamelly.com`として公開されています。

## エンドポイント

| パス | 用途 |
|------|------|
| `GET /healthz` | ヘルスチェック |
| `GET /check` | 判定ロジックの動作確認用（3レポートの完成状況をJSONで返す） |
| `POST /send-test` | SMTP送信の動作確認用（固定のテストアドレスへ送信） |
| `POST /slack/commands` | Slack Slash Command（`/check-reports`）の受信先 |
| `POST /slack/interactions` | Slackボタン押下（Interactivity）の受信先 |

`/slack/commands`は`/check-reports test`のように引数に`test`を付けると、実際の判定をスキップして強制的に「完成」扱いの確認メッセージを表示します（動作確認用。本番運用前に削除・無効化すること）。

## 必要な環境変数

| 変数名 | 用途 |
|--------|------|
| `PORT` | リッスンポート（省略時 `8080`） |
| `SMTP_HOST` / `SMTP_PORT` | SMTPサーバー（`mail.bold.ne.jp` / `587`） |
| `SMTP_TLS_SERVER_NAME` | STARTTLS証明書検証に使うホスト名（共有ホスティングのため`SMTP_HOST`と別名になる場合に指定） |
| `SMTP_USERNAME` / `SMTP_PASSWORD` | SMTP認証情報 |
| `SHEETS_SERVICE_ACCOUNT_FILE` | Google Sheets/Drive APIのサービスアカウントJSONファイルのパス |
| `SLACK_SIGNING_SECRET` | SlackリクエストのHMAC署名検証用シークレット |

いずれも`infra`リポジトリ側でk8s Secret（SOPS+ageで暗号化）としてコンテナに配線されています。

## ローカルでの実行

```bash
go build -o /tmp/report-bot .
SHEETS_SERVICE_ACCOUNT_FILE=/path/to/service-account.json \
  SMTP_HOST=mail.bold.ne.jp SMTP_PORT=587 SMTP_USERNAME=... SMTP_PASSWORD=... \
  SLACK_SIGNING_SECRET=dummy \
  PORT=18080 /tmp/report-bot
```
