package main

import (
	"context"
	"encoding/json"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"
)

func main() {
	port := os.Getenv("PORT")
	if port == "" {
		port = "8080"
	}

	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("ok"))
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		_, _ = w.Write([]byte("report-bot is running\n"))
	})
	// SMTP送信の動作確認用。宛先はテスト固定(testRecipient)に送る。
	mux.HandleFunc("/send-test", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			return
		}
		cfg, err := smtpConfigFromEnv()
		if err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		if err := sendMail(cfg, testRecipient, "report-bot SMTPテスト", "report-botからのSMTP送信テストです。"); err != nil {
			log.Printf("send-test failed: %v", err)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		log.Printf("send-test succeeded: to=%s", testRecipient)
		w.WriteHeader(http.StatusOK)
		_, _ = w.Write([]byte("sent\n"))
	})
	// 判定ロジックの動作確認用。3レポートの完成状況をJSONで返す。
	mux.HandleFunc("/check", func(w http.ResponseWriter, r *http.Request) {
		ctx, cancel := context.WithTimeout(r.Context(), 20*time.Second)
		defer cancel()
		results, err := checkAllReports(ctx)
		if err != nil {
			log.Printf("check failed: %v", err)
			http.Error(w, err.Error(), http.StatusInternalServerError)
			return
		}
		for _, res := range results {
			log.Printf("check: %s complete=%v missing=%v", res.Name, res.IsComplete, res.Missing)
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(results)
	})
	mux.HandleFunc("/slack/commands", handleSlashCommand)
	mux.HandleFunc("/slack/interactions", handleInteraction)

	srv := &http.Server{
		Addr:         ":" + port,
		Handler:      mux,
		ReadTimeout:  5 * time.Second,
		WriteTimeout: 10 * time.Second,
	}

	go func() {
		log.Printf("listening on :%s", port)
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			log.Fatalf("server error: %v", err)
		}
	}()

	// k8sがPod終了時に送るSIGTERMを受けて、既存リクエストの完了を待ってから終了する
	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGTERM, syscall.SIGINT)
	<-stop

	log.Println("shutting down...")
	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()
	if err := srv.Shutdown(ctx); err != nil {
		log.Fatalf("graceful shutdown failed: %v", err)
	}
	log.Println("shutdown complete")
}
