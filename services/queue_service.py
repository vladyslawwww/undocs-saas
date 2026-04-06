# services/queue_service.py
import os

from qstash import QStash


def publish_document_job(doc_id):
    """Pushes a job to QStash to process later using regional endpoints."""
    qstash_token = os.getenv("QSTASH_TOKEN")
    # Explicitly pull the regional URL or fallback to global
    qstash_url = os.getenv("QSTASH_URL", "https://qstash.upstash.io")
    base_url = os.getenv("BASE_URL")

    if not qstash_token or not base_url:
        print("⚠️ QStash config missing. Falling back to synchronous processing.")
        return False

    # Pass the regional URL to the Client constructor
    client = QStash(token=qstash_token, url=qstash_url)

    target_url = f"{base_url.rstrip('/')}/api/internal/process-doc"

    try:
        client.message.publish_json(url=target_url, body={"doc_id": doc_id})
        return True
    except Exception as e:
        print(f"QStash Regional Publish Error: {e}")
        return False
