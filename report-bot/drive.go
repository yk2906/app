package main

import (
	"context"
	"fmt"
	"io"

	"google.golang.org/api/drive/v3"
	"google.golang.org/api/option"
)

const xlsxMimeType = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

func buildDriveClient(ctx context.Context) (*drive.Service, error) {
	creds, err := loadGoogleCredentials(ctx, drive.DriveReadonlyScope)
	if err != nil {
		return nil, err
	}
	return drive.NewService(ctx, option.WithCredentials(creds))
}

// exportAsXlsx はGoogleスプレッドシートをxlsx形式でエクスポートする。
func exportAsXlsx(ctx context.Context, svc *drive.Service, fileID string) ([]byte, error) {
	resp, err := svc.Files.Export(fileID, xlsxMimeType).Download()
	if err != nil {
		return nil, fmt.Errorf("ファイル(%s)のエクスポートに失敗: %w", fileID, err)
	}
	defer resp.Body.Close()

	data, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("ファイル(%s)の読み込みに失敗: %w", fileID, err)
	}
	return data, nil
}
