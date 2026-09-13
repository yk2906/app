package main

import (
	"crypto/tls"
	"encoding/base64"
	"fmt"
	"mime"
	"net"
	"net/smtp"
	"net/url"
	"os"
	"strings"
)

type mailAttachment struct {
	filename string
	content  []byte
}

type smtpConfig struct {
	host          string
	port          string
	username      string
	password      string
	tlsServerName string
}

func smtpConfigFromEnv() (smtpConfig, error) {
	cfg := smtpConfig{
		host:     os.Getenv("SMTP_HOST"),
		port:     os.Getenv("SMTP_PORT"),
		username: os.Getenv("SMTP_USERNAME"),
		password: os.Getenv("SMTP_PASSWORD"),
		// mail.bold.ne.jpは共有ホスティング(extremeserv.net)経由で、
		// 提示される証明書はSMTP_HOSTとは別名(*.extremeserv.net)になっている。
		// 未設定ならSMTP_HOSTをそのまま証明書検証に使う。
		tlsServerName: os.Getenv("SMTP_TLS_SERVER_NAME"),
	}
	if cfg.host == "" || cfg.port == "" || cfg.username == "" || cfg.password == "" {
		return cfg, fmt.Errorf("SMTP_HOST/SMTP_PORT/SMTP_USERNAME/SMTP_PASSWORD が設定されていません")
	}
	if cfg.tlsServerName == "" {
		cfg.tlsServerName = cfg.host
	}
	return cfg, nil
}

// sendMail はSTARTTLS(587)経由で添付なしのメールを送信する。
func sendMail(cfg smtpConfig, to, subject, body string) error {
	msg := []byte(fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n%s\r\n",
		cfg.username, to, mime.QEncoding.Encode("UTF-8", subject), body))
	return dialAndSend(cfg, to, nil, msg)
}

// sendMailWithAttachments はSTARTTLS(587)経由で添付ファイル付きのメールを送信する。
func sendMailWithAttachments(cfg smtpConfig, to string, cc []string, subject, body string, attachments []mailAttachment) error {
	msg, err := buildMultipartMessage(cfg.username, to, cc, subject, body, attachments)
	if err != nil {
		return fmt.Errorf("メール本文の組み立てに失敗: %w", err)
	}
	return dialAndSend(cfg, to, cc, msg)
}

func buildMultipartMessage(from, to string, cc []string, subject, body string, attachments []mailAttachment) ([]byte, error) {
	const boundary = "report-bot-boundary"
	var b strings.Builder

	fmt.Fprintf(&b, "From: %s\r\n", from)
	fmt.Fprintf(&b, "To: %s\r\n", to)
	if len(cc) > 0 {
		fmt.Fprintf(&b, "Cc: %s\r\n", strings.Join(cc, ", "))
	}
	fmt.Fprintf(&b, "Subject: %s\r\n", mime.QEncoding.Encode("UTF-8", subject))
	fmt.Fprintf(&b, "MIME-Version: 1.0\r\n")
	fmt.Fprintf(&b, "Content-Type: multipart/mixed; boundary=%s\r\n\r\n", boundary)

	fmt.Fprintf(&b, "--%s\r\n", boundary)
	fmt.Fprintf(&b, "Content-Type: text/plain; charset=UTF-8\r\n\r\n")
	fmt.Fprintf(&b, "%s\r\n\r\n", body)

	for _, att := range attachments {
		fmt.Fprintf(&b, "--%s\r\n", boundary)
		fmt.Fprintf(&b, "Content-Type: application/octet-stream\r\n")
		fmt.Fprintf(&b, "Content-Transfer-Encoding: base64\r\n")
		fmt.Fprintf(&b, "Content-Disposition: attachment; filename*=UTF-8''%s\r\n\r\n", url.PathEscape(att.filename))

		encoded := base64.StdEncoding.EncodeToString(att.content)
		for i := 0; i < len(encoded); i += 76 {
			end := i + 76
			if end > len(encoded) {
				end = len(encoded)
			}
			b.WriteString(encoded[i:end])
			b.WriteString("\r\n")
		}
		b.WriteString("\r\n")
	}
	fmt.Fprintf(&b, "--%s--\r\n", boundary)

	return []byte(b.String()), nil
}

// dialAndSend はSTARTTLS(587)でSMTP接続し、組み立て済みのメッセージを送信する。
// net/smtp.SendMailはサーバーがSTARTTLSに対応していても自動で使わないため、手動でハンドシェイクする。
func dialAndSend(cfg smtpConfig, to string, cc []string, msg []byte) error {
	addr := net.JoinHostPort(cfg.host, cfg.port)

	client, err := smtp.Dial(addr)
	if err != nil {
		return fmt.Errorf("SMTP接続に失敗: %w", err)
	}
	defer client.Close()

	if err := client.StartTLS(&tls.Config{ServerName: cfg.tlsServerName}); err != nil {
		return fmt.Errorf("STARTTLSに失敗: %w", err)
	}

	auth := smtp.PlainAuth("", cfg.username, cfg.password, cfg.host)
	if err := client.Auth(auth); err != nil {
		return fmt.Errorf("SMTP認証に失敗: %w", err)
	}

	if err := client.Mail(cfg.username); err != nil {
		return fmt.Errorf("MAIL FROMに失敗: %w", err)
	}
	recipients := append([]string{to}, cc...)
	for _, rcpt := range recipients {
		if err := client.Rcpt(rcpt); err != nil {
			return fmt.Errorf("RCPT TO(%s)に失敗: %w", rcpt, err)
		}
	}

	wc, err := client.Data()
	if err != nil {
		return fmt.Errorf("DATA開始に失敗: %w", err)
	}
	if _, err := wc.Write(msg); err != nil {
		return fmt.Errorf("本文書き込みに失敗: %w", err)
	}
	if err := wc.Close(); err != nil {
		return fmt.Errorf("送信の確定に失敗: %w", err)
	}

	return client.Quit()
}
