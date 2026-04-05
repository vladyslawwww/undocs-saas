import requests

# CONFIG
API_URL = "http://127.0.0.1:5000/api/ingest"
API_KEY = "<undocs-workspace-api-key>"
SCHEMA_NAME = "<name-of-the-schema-created-in-the-workspace>"
FILE_PATH = "<path-to-your-testing-pdf>"


def run():
    print(f"Sending {FILE_PATH}...")
    try:
        with open(FILE_PATH, "rb") as f:
            r = requests.post(
                API_URL,
                headers={"X-API-Key": API_KEY},
                data={"schema_name": SCHEMA_NAME},
                files={"file": f},
            )
        print(f"Status: {r.status_code}")
        print(f"Body: {r.json()}")
    except Exception as e:
        print(f"Failed: {e}")


if __name__ == "__main__":
    run()
