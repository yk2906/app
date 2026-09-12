package main

import (
	"crypto/tls"
	"fmt"
	"net"
	"net/smtp"
	"os"
)

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

// sendMail はSTARTTLS(587)経由でメールを送信する。net/smtp.SendMailは
// サーバーがSTARTTLSに対応していても自動で使わないため、手動でハンドシェイクする。
func sendMail(cfg smtpConfig, to, subject, body string) error {
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
	if err := client.Rcpt(to); err != nil {
		return fmt.Errorf("RCPT TOに失敗: %w", err)
	}

	wc, err := client.Data()
	if err != nil {
		return fmt.Errorf("DATA開始に失敗: %w", err)
	}
	msg := fmt.Sprintf("From: %s\r\nTo: %s\r\nSubject: %s\r\nContent-Type: text/plain; charset=UTF-8\r\n\r\n%s\r\n",
		cfg.username, to, subject, body)
	if _, err := wc.Write([]byte(msg)); err != nil {
		return fmt.Errorf("本文書き込みに失敗: %w", err)
	}
	if err := wc.Close(); err != nil {
		return fmt.Errorf("送信の確定に失敗: %w", err)
	}

	return client.Quit()
}
