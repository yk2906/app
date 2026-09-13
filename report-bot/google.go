package main

import (
	"context"
	"fmt"
	"os"

	"golang.org/x/oauth2/google"
)

// loadGoogleCredentials はSHEETS_SERVICE_ACCOUNT_FILEで指定されたサービスアカウントJSONを
// 読み込み、指定スコープの認証情報を返す。Sheets/Drive両方のクライアントで共用する。
func loadGoogleCredentials(ctx context.Context, scope string) (*google.Credentials, error) {
	credsFile := os.Getenv("SHEETS_SERVICE_ACCOUNT_FILE")
	if credsFile == "" {
		return nil, fmt.Errorf("SHEETS_SERVICE_ACCOUNT_FILE が設定されていません")
	}
	data, err := os.ReadFile(credsFile)
	if err != nil {
		return nil, fmt.Errorf("サービスアカウントファイルの読み込みに失敗: %w", err)
	}
	creds, err := google.CredentialsFromJSON(ctx, data, scope)
	if err != nil {
		return nil, fmt.Errorf("認証情報の読み込みに失敗: %w", err)
	}
	return creds, nil
}
