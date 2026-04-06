# routes/internal.py
import os
import threading

from flask import Blueprint, current_app, jsonify, request
from qstash import Receiver

from services.ai_service import process_document_logic

internal_bp = Blueprint("internal", __name__, url_prefix="/api/internal")


@internal_bp.route("/process-doc", methods=["POST"])
def process_doc_webhook():
    """Triggered by QStash to process a document"""
    signature = request.headers.get("Upstash-Signature")
    # QStash requires the raw string body to verify the cryptographic signature
    body = request.get_data(as_text=True)

    receiver = Receiver(
        current_signing_key=os.getenv("QSTASH_CURRENT_SIGNING_KEY", ""),
        next_signing_key=os.getenv("QSTASH_NEXT_SIGNING_KEY", ""),
    )

    try:
        # Verify the request actually came from Upstash
        receiver.verify(body=body, signature=signature, url=request.url)
    except Exception as e:
        print(f"QStash Verification Failed: {e}")
        return jsonify({"error": "Invalid signature"}), 401

    data = request.json
    doc_id = data.get("doc_id")

    if not doc_id:
        return jsonify({"error": "Missing doc_id"}), 400

    app_obj = current_app._get_current_object()
    threading.Thread(target=process_document_logic, args=(app_obj, doc_id)).start()

    return jsonify({"status": "processing_started", "doc_id": doc_id}), 200
