# services/queue_service.py
import os

from qstash import QStash


def publish_document_job(doc_id):
    """Pushes a job to QStash to process later."""
    qstash_token = os.getenv("QSTASH_TOKEN")
    base_url = os.getenv("BASE_URL")  # e.g., https://your-app.onrender.com

    if not qstash_token or not base_url:
        print(
            "⚠️ QStash config missing. Falling back to synchronous processing (Not for Prod!)"
        )
        return False

    client = QStash(qstash_token)
    target_url = f"{base_url.rstrip('/')}/api/internal/process-doc"

    try:
        # Publish the webhook trigger to QStash
        client.message.publish_json(url=target_url, body={"doc_id": doc_id})
        return True
    except Exception as e:
        print(f"QStash Publish Error: {e}")
        return False
