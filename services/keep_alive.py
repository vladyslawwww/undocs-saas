import os
import threading
import time

import requests


def ping_self():
    """
    Background worker that pings the public URL to prevent Render spin-down.
    """
    # Wait for the server to actually start up first
    time.sleep(20)

    base_url = os.getenv("BASE_URL")
    if not base_url or "localhost" in base_url:
        print("⚠️ Keep-alive skipped: BASE_URL is local or missing.")
        return

    print(f"🚀 Keep-alive thread started for: {base_url}")

    while True:
        try:
            # We hit the landing page
            response = requests.get(base_url, timeout=10)
            print(f"❤️ Heartbeat sent to {base_url} - Status: {response.status_code}")
        except Exception as e:
            print(f"💔 Heartbeat failed: {e}")

        # Sleep for 800 seconds
        # Render's timeout is 15 minutes.
        time.sleep(800)


def start_keep_alive():
    """Starts the heartbeat in a non-blocking daemon thread."""
    thread = threading.Thread(target=ping_self, daemon=True)
    thread.start()
