package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"sync"
	"time"
)

const (
	testRecipient    = "y_kohama@bold.ne.jp"
	mailSubject      = "【テスト】【公式レポート提出】1495・小濵佑斗"
	mailBodyTmpl     = "経営戦略本部　管理部各位\n\nお疲れ様です。\n\n今月のABC目標に関するレポートを提出致します。\n・Udemy受講レポート（2つ）\n・自主勉強会開催レポート\n\n以上、よろしくお願いします。\n\n※このメールはreport-bot経由のテスト送信です。宛先は本番のjinji@bold.ne.jpではなくテストアドレスに固定しています。"
	sendReportAction = "send_report"
)

// 判定完了後、ボタン押下までの間、下書き内容をメモリ上に保持しておく。
// 単一レプリカ運用のため外部ストアは使わない。
var draftStore = struct {
	sync.Mutex
	drafts map[string]bool // key: monthKey, value: 完成しているか(常にtrueのみ格納)
}{drafts: make(map[string]bool)}

func monthKey(t time.Time) string {
	return fmt.Sprintf("%04d-%02d", t.Year(), int(t.Month()))
}

// verifySlackSignature はSlackの署名検証(v0)を行う。
// https://api.slack.com/authentication/verifying-requests-from-slack
func verifySlackSignature(r *http.Request, body []byte, signingSecret string) bool {
	timestamp := r.Header.Get("X-Slack-Request-Timestamp")
	sig := r.Header.Get("X-Slack-Signature")
	if timestamp == "" || sig == "" || signingSecret == "" {
		return false
	}

	ts, err := strconv.ParseInt(timestamp, 10, 64)
	if err != nil {
		return false
	}
	if diff := time.Since(time.Unix(ts, 0)); diff > 5*time.Minute || diff < -5*time.Minute {
		return false // リプレイ攻撃対策
	}

	base := "v0:" + timestamp + ":" + string(body)
	mac := hmac.New(sha256.New, []byte(signingSecret))
	mac.Write([]byte(base))
	expected := "v0=" + hex.EncodeToString(mac.Sum(nil))

	return hmac.Equal([]byte(expected), []byte(sig))
}

func postToResponseURL(responseURL string, payload map[string]interface{}) {
	data, err := json.Marshal(payload)
	if err != nil {
		log.Printf("response_urlペイロードの組み立てに失敗: %v", err)
		return
	}
	resp, err := http.Post(responseURL, "application/json", strings.NewReader(string(data)))
	if err != nil {
		log.Printf("response_urlへの送信に失敗: %v", err)
		return
	}
	defer resp.Body.Close()
	log.Printf("response_urlへ送信しました: status=%d", resp.StatusCode)
}

func missingListBlocksText(results []checkResult) string {
	var b strings.Builder
	b.WriteString("今月のレポートがまだ揃っていません:\n")
	for _, r := range results {
		if r.IsComplete {
			continue
		}
		fmt.Fprintf(&b, "*%s*\n", r.Name)
		for _, item := range r.Missing {
			fmt.Fprintf(&b, "    • %s\n", item)
		}
	}
	return b.String()
}

func draftSummaryText(today time.Time) string {
	var b strings.Builder
	b.WriteString("今月のレポートは全て完成しています。以下の内容で送信できます:\n")
	fmt.Fprintf(&b, "*宛先(テスト):* %s\n", testRecipient)
	fmt.Fprintf(&b, "*件名:* %s\n", mailSubject)
	b.WriteString("*本文:*\n```\n" + mailBodyTmpl + "\n```\n")
	b.WriteString("*添付ファイル:*\n")
	for _, r := range reports {
		fmt.Fprintf(&b, "    • %s.xlsx\n", r.name)
	}
	return b.String()
}

// readVerifiedSlackForm はSlackからのリクエストを署名検証したうえでフォームとして解析する。
// 検証・解析に失敗した場合はレスポンスを書き込み済みで false を返す。
func readVerifiedSlackForm(w http.ResponseWriter, r *http.Request) (url.Values, bool) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, "リクエストの読み込みに失敗しました", http.StatusBadRequest)
		return nil, false
	}
	if !verifySlackSignature(r, body, os.Getenv("SLACK_SIGNING_SECRET")) {
		http.Error(w, "署名検証に失敗しました", http.StatusUnauthorized)
		return nil, false
	}
	values, err := url.ParseQuery(string(body))
	if err != nil {
		http.Error(w, "リクエストの解析に失敗しました", http.StatusBadRequest)
		return nil, false
	}
	return values, true
}

func handleSlashCommand(w http.ResponseWriter, r *http.Request) {
	values, ok := readVerifiedSlackForm(w, r)
	if !ok {
		return
	}
	responseURL := values.Get("response_url")
	isTestMode := strings.TrimSpace(values.Get("text")) == "test"

	// Slackは3秒以内の応答を要求するため、先にACKだけ返す
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(map[string]string{"text": "チェック中です..."})

	go func() {
		if isTestMode {
			// 動作確認用: 判定をスキップして強制的に「完成」扱いの確認メッセージを出す。
			log.Printf("test mode: 判定をスキップして送信確認メッセージを表示します")
			postDraftMessage(responseURL, time.Now())
			return
		}

		ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
		defer cancel()

		results, err := checkAllReports(ctx)
		if err != nil {
			log.Printf("check failed: %v", err)
			postToResponseURL(responseURL, map[string]interface{}{
				"text": fmt.Sprintf("判定中にエラーが発生しました: %v", err),
			})
			return
		}

		allComplete := true
		for _, res := range results {
			if !res.IsComplete {
				allComplete = false
			}
		}

		if !allComplete {
			postToResponseURL(responseURL, map[string]interface{}{
				"text": missingListBlocksText(results),
			})
			return
		}

		postDraftMessage(responseURL, time.Now())
	}()
}

func postDraftMessage(responseURL string, today time.Time) {
	key := monthKey(today)
	draftStore.Lock()
	draftStore.drafts[key] = true
	draftStore.Unlock()

	summary := draftSummaryText(today)
	postToResponseURL(responseURL, map[string]interface{}{
		"text": summary,
		"blocks": []map[string]interface{}{
			{
				"type": "section",
				"text": map[string]string{"type": "mrkdwn", "text": summary},
			},
			{
				"type": "actions",
				"elements": []map[string]interface{}{
					{
						"type":      "button",
						"text":      map[string]string{"type": "plain_text", "text": "送信"},
						"action_id": sendReportAction,
						"value":     key,
						"style":     "primary",
					},
				},
			},
		},
	})
}

type slackInteractionPayload struct {
	ResponseURL string `json:"response_url"`
	Actions     []struct {
		ActionID string `json:"action_id"`
		Value    string `json:"value"`
	} `json:"actions"`
}

func handleInteraction(w http.ResponseWriter, r *http.Request) {
	values, ok := readVerifiedSlackForm(w, r)
	if !ok {
		return
	}

	var payload slackInteractionPayload
	if err := json.Unmarshal([]byte(values.Get("payload")), &payload); err != nil {
		http.Error(w, "ペイロードの解析に失敗しました", http.StatusBadRequest)
		return
	}
	if len(payload.Actions) == 0 {
		w.WriteHeader(http.StatusOK)
		return
	}
	action := payload.Actions[0]

	w.WriteHeader(http.StatusOK)

	go func() {
		if action.ActionID != sendReportAction {
			return
		}

		draftStore.Lock()
		_, ok := draftStore.drafts[action.Value]
		draftStore.Unlock()
		if !ok {
			postToResponseURL(payload.ResponseURL, map[string]interface{}{
				"replace_original": true,
				"text":             "下書きが見つかりませんでした（判定からやり直してください）",
			})
			return
		}

		if err := sendDraftReport(); err != nil {
			log.Printf("send failed: %v", err)
			postToResponseURL(payload.ResponseURL, map[string]interface{}{
				"replace_original": true,
				"text":             fmt.Sprintf("送信に失敗しました: %v", err),
			})
			return
		}

		draftStore.Lock()
		delete(draftStore.drafts, action.Value)
		draftStore.Unlock()

		postToResponseURL(payload.ResponseURL, map[string]interface{}{
			"replace_original": true,
			"text":             fmt.Sprintf("✅ 送信しました（%s、宛先: %s）", time.Now().Format("2006-01-02 15:04"), testRecipient),
		})
	}()
}

func sendDraftReport() error {
	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
	defer cancel()

	driveSvc, err := buildDriveClient(ctx)
	if err != nil {
		return fmt.Errorf("Driveクライアントの初期化に失敗: %w", err)
	}

	attachments := make([]mailAttachment, 0, len(reports))
	for _, report := range reports {
		data, err := exportAsXlsx(ctx, driveSvc, report.fileID)
		if err != nil {
			return err
		}
		attachments = append(attachments, mailAttachment{
			filename: report.name + ".xlsx",
			content:  data,
		})
	}

	smtpCfg, err := smtpConfigFromEnv()
	if err != nil {
		return err
	}

	return sendMailWithAttachments(smtpCfg, testRecipient, nil, mailSubject, mailBodyTmpl, attachments)
}
