import time
import os

def main():
    print("--- Steam Bot Lifecycle Started ---", flush=True)
    env_test = os.getenv("APP_ENV", "local-test")
    print(f"Current Environment: {env_test}")

    while True:
        print("Bot is running and waiting for Steam API integration...")
        time.sleep(60) # 1分ごとにログを出す

if __name__ == "__main__":
    main()