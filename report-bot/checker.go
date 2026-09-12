package main

import (
	"context"
	"fmt"
	"os"
	"regexp"
	"strconv"
	"strings"
	"time"

	"golang.org/x/oauth2/google"
	"google.golang.org/api/option"
	"google.golang.org/api/sheets/v4"
)

// 受講時間・学習時間はこの分数未満なら未完了とする
const minStudyMinutes = 120

type reportSpec struct {
	name       string
	fileID     string
	reportType string // "udemy" or "jishu"
}

var reports = []reportSpec{
	{name: "【項番2】Udemy受講レポート", fileID: "1TopTSdoMCM-FsLZyyJyppt_6v3JbK4L38kbQErN0x58", reportType: "udemy"},
	{name: "【項番3】Udemy受講レポート", fileID: "1JKofkpoV4OWNSc33byyEmDThI_RJra50BBJRibkxTmE", reportType: "udemy"},
	{name: "【項番4】自主勉強会開催レポート", fileID: "1K4j1_OqP11g2KUy-XQwcA5R-_ooKt0G9aAL_HOVwvv4", reportType: "jishu"},
}

type tocColumn struct {
	col   string
	label string
}

var tocColumnsByType = map[string][]tocColumn{
	"udemy": {{"C", "受講日"}, {"D", "講師"}, {"E", "コース名"}, {"F", "受講時間"}},
	"jishu": {{"C", "開催日"}, {"D", "主催者"}, {"E", "講義名"}, {"I", "出席者"}},
}

// 目次!C5:I10 の相対インデックス
var tocColumnIndex = map[string]int{"C": 0, "D": 1, "E": 2, "F": 3, "I": 6}

var udemySessionCells = []string{"E9", "E10", "E11", "E12", "E13", "E14", "E15", "E16"}
var udemySessionTimeCells = []string{"S9", "S10", "S11", "S12", "S13", "S14", "S15", "S16"}

type fixedCell struct {
	cell     string
	label    string
	required bool
}

var udemyFixedCells = []fixedCell{
	{"X9", "学習時間", true},
	{"D17", "内容", true},
	{"B23", "学んだこと", true},
	{"B30", "今後の活用", false},
}

var jishuFixedCells = []fixedCell{
	{"E8", "開催日", true},
	{"N8", "実施時間", true},
	{"R8", "主催者", true},
	{"E9", "受講者", true},
	{"D10", "内容", true},
	{"B15", "目的", true},
	{"B22", "受講者の反応", true},
	{"B28", "開催内容の反省点、次回の改善点", true},
}

var googleSheetsEpoch = time.Date(1899, 12, 30, 0, 0, 0, 0, time.UTC)

var hoursPattern = regexp.MustCompile(`(\d+)\s*時間`)
var minutesPattern = regexp.MustCompile(`(\d+)\s*分`)
var sheetMonthPattern = regexp.MustCompile(`(\d{2})月\d{2}日`)

// parseStudyMinutes は「2時間4分」「1時間」「39分」のような文字列を分に変換する。
// 時間・分どちらも無ければ(-1, false)を返す。
func parseStudyMinutes(text string) (int, bool) {
	hoursMatch := hoursPattern.FindStringSubmatch(text)
	minutesMatch := minutesPattern.FindStringSubmatch(text)
	if hoursMatch == nil && minutesMatch == nil {
		return 0, false
	}
	hours := 0
	if hoursMatch != nil {
		hours, _ = strconv.Atoi(hoursMatch[1])
	}
	minutes := 0
	if minutesMatch != nil {
		minutes, _ = strconv.Atoi(minutesMatch[1])
	}
	return hours*60 + minutes, true
}

func buildSheetsClient(ctx context.Context) (*sheets.Service, error) {
	credsFile := os.Getenv("SHEETS_SERVICE_ACCOUNT_FILE")
	if credsFile == "" {
		return nil, fmt.Errorf("SHEETS_SERVICE_ACCOUNT_FILE が設定されていません")
	}
	data, err := os.ReadFile(credsFile)
	if err != nil {
		return nil, fmt.Errorf("サービスアカウントファイルの読み込みに失敗: %w", err)
	}
	creds, err := google.CredentialsFromJSON(ctx, data, sheets.SpreadsheetsReadonlyScope)
	if err != nil {
		return nil, fmt.Errorf("認証情報の読み込みに失敗: %w", err)
	}
	return sheets.NewService(ctx, option.WithCredentials(creds))
}

func serialToDate(serial string) (time.Time, bool) {
	f, err := strconv.ParseFloat(serial, 64)
	if err != nil {
		return time.Time{}, false
	}
	return googleSheetsEpoch.Add(time.Duration(f * 24 * float64(time.Hour))), true
}

func findCurrentMonthTocRow(svc *sheets.Service, fileID string, today time.Time) ([]interface{}, error) {
	resp, err := svc.Spreadsheets.Values.Get(fileID, "目次!C5:I10").Do()
	if err != nil {
		return nil, fmt.Errorf("目次シートの取得に失敗: %w", err)
	}
	for _, row := range resp.Values {
		if len(row) == 0 {
			continue
		}
		serialStr := fmt.Sprintf("%v", row[0])
		date, ok := serialToDate(serialStr)
		if !ok {
			continue
		}
		if date.Year() == today.Year() && date.Month() == today.Month() {
			return row, nil
		}
	}
	return nil, nil
}

func cellStr(row []interface{}, idx int) string {
	if row == nil || idx >= len(row) {
		return ""
	}
	return strings.TrimSpace(fmt.Sprintf("%v", row[idx]))
}

func tocMissingColumns(row []interface{}, reportType string) []string {
	var missing []string
	for _, tc := range tocColumnsByType[reportType] {
		idx := tocColumnIndex[tc.col]
		value := cellStr(row, idx)
		if value == "" {
			missing = append(missing, fmt.Sprintf("目次:%s", tc.label))
		} else if tc.col == "F" && reportType == "udemy" {
			minutes, ok := parseStudyMinutes(value)
			if !ok || minutes < minStudyMinutes {
				missing = append(missing, fmt.Sprintf("目次:%s（2時間未満）", tc.label))
			}
		}
	}
	return missing
}

func findCurrentMonthSheetName(svc *sheets.Service, fileID string, today time.Time) (string, error) {
	meta, err := svc.Spreadsheets.Get(fileID).Fields("sheets.properties.title").Do()
	if err != nil {
		return "", fmt.Errorf("スプレッドシート情報の取得に失敗: %w", err)
	}
	monthStr := fmt.Sprintf("%02d月", int(today.Month()))
	for _, sheet := range meta.Sheets {
		title := sheet.Properties.Title
		if title == "目次" || !strings.Contains(title, monthStr) {
			continue
		}
		match := sheetMonthPattern.FindStringSubmatch(title)
		if match != nil && match[1] == fmt.Sprintf("%02d", int(today.Month())) {
			return title, nil
		}
	}
	return "", nil
}

func getCellValues(svc *sheets.Service, fileID, sheetName string, cells []string) ([]string, error) {
	ranges := make([]string, len(cells))
	for i, c := range cells {
		ranges[i] = fmt.Sprintf("'%s'!%s", sheetName, c)
	}
	resp, err := svc.Spreadsheets.Values.BatchGet(fileID).Ranges(ranges...).Do()
	if err != nil {
		return nil, fmt.Errorf("セル取得に失敗: %w", err)
	}
	values := make([]string, len(cells))
	for i, vr := range resp.ValueRanges {
		if len(vr.Values) > 0 && len(vr.Values[0]) > 0 {
			values[i] = fmt.Sprintf("%v", vr.Values[0][0])
		}
	}
	return values, nil
}

func checkUdemyReport(svc *sheets.Service, fileID, sheetName string) ([]string, error) {
	var missing []string

	allCells := append(append([]string{}, udemySessionCells...), udemySessionTimeCells...)
	allValues, err := getCellValues(svc, fileID, sheetName, allCells)
	if err != nil {
		return nil, err
	}
	sessionValues := allValues[:len(udemySessionCells)]
	timeValues := allValues[len(udemySessionCells):]

	hasFilledSession := false
	for _, v := range sessionValues {
		if strings.TrimSpace(v) != "" {
			hasFilledSession = true
			break
		}
	}
	if !hasFilledSession {
		missing = append(missing, "本文:セッション（最低1件）")
	}
	for i := range sessionValues {
		rowNum := 9 + i
		if strings.TrimSpace(sessionValues[i]) != "" && strings.TrimSpace(timeValues[i]) == "" {
			missing = append(missing, fmt.Sprintf("本文:時間（%d行目のセッションに対応する時間が未入力）", rowNum))
		}
	}

	fixedCellsList := make([]string, len(udemyFixedCells))
	for i, fc := range udemyFixedCells {
		fixedCellsList[i] = fc.cell
	}
	fixedValues, err := getCellValues(svc, fileID, sheetName, fixedCellsList)
	if err != nil {
		return nil, err
	}
	for i, fc := range udemyFixedCells {
		value := strings.TrimSpace(fixedValues[i])
		if fc.required && value == "" {
			missing = append(missing, fmt.Sprintf("本文:%s", fc.label))
		} else if fc.cell == "X9" && value != "" {
			minutes, ok := parseStudyMinutes(value)
			if !ok || minutes < minStudyMinutes {
				missing = append(missing, fmt.Sprintf("本文:%s（2時間未満）", fc.label))
			}
		}
	}

	return missing, nil
}

func checkJishuReport(svc *sheets.Service, fileID, sheetName string) ([]string, error) {
	var missing []string
	cells := make([]string, len(jishuFixedCells))
	for i, fc := range jishuFixedCells {
		cells[i] = fc.cell
	}
	values, err := getCellValues(svc, fileID, sheetName, cells)
	if err != nil {
		return nil, err
	}
	for i, fc := range jishuFixedCells {
		if fc.required && strings.TrimSpace(values[i]) == "" {
			missing = append(missing, fmt.Sprintf("本文:%s", fc.label))
		}
	}
	return missing, nil
}

type checkResult struct {
	Name       string   `json:"name"`
	IsComplete bool     `json:"is_complete"`
	Missing    []string `json:"missing"`
}

func checkReport(svc *sheets.Service, report reportSpec, today time.Time) (checkResult, error) {
	result := checkResult{Name: report.name}

	tocRow, err := findCurrentMonthTocRow(svc, report.fileID, today)
	if err != nil {
		return result, err
	}
	result.Missing = append(result.Missing, tocMissingColumns(tocRow, report.reportType)...)

	sheetName, err := findCurrentMonthSheetName(svc, report.fileID, today)
	if err != nil {
		return result, err
	}
	if sheetName == "" {
		result.Missing = append(result.Missing, "本文:今月のシートがまだ作成されていません")
	} else if report.reportType == "udemy" {
		missing, err := checkUdemyReport(svc, report.fileID, sheetName)
		if err != nil {
			return result, err
		}
		result.Missing = append(result.Missing, missing...)
	} else {
		missing, err := checkJishuReport(svc, report.fileID, sheetName)
		if err != nil {
			return result, err
		}
		result.Missing = append(result.Missing, missing...)
	}

	result.IsComplete = len(result.Missing) == 0
	return result, nil
}

func checkAllReports(ctx context.Context) ([]checkResult, error) {
	svc, err := buildSheetsClient(ctx)
	if err != nil {
		return nil, err
	}
	today := time.Now()

	results := make([]checkResult, 0, len(reports))
	for _, report := range reports {
		result, err := checkReport(svc, report, today)
		if err != nil {
			return nil, fmt.Errorf("%s の判定に失敗: %w", report.name, err)
		}
		results = append(results, result)
	}
	return results, nil
}
