import os
import threading
import uuid

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from models import DocSchema, Document, Project, db
from services.ai_service import process_document_background

api_bp = Blueprint("api", __name__, url_prefix="/api")


@api_bp.route("/ingest", methods=["POST"])
def ingest():
    api_key = request.headers.get("X-API-Key")
    project = Project.query.filter_by(api_key=api_key).first()

    if not project:
        return jsonify({"error": "Invalid API Key"}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    schema_name = request.form.get("schema_name")

    schema = DocSchema.query.filter_by(project_id=project.id, name=schema_name).first()
    if not schema:
        return jsonify({"error": f"Schema '{schema_name}' not found in project"}), 404

    # --- UNIQUE FILENAME GENERATION ---
    original_name = secure_filename(file.filename)
    unique_prefix = str(uuid.uuid4())[:8]
    storage_name = f"{unique_prefix}_{original_name}"

    # Save file
    save_path = os.path.join("static/uploads", storage_name)
    file.save(save_path)

    # Create DB Entry
    doc = Document(
        filename=original_name,  # User sees this
        storage_filename=storage_name,  # Disk uses this
        schema_id=schema.id,
        status="QUEUED",
    )
    db.session.add(doc)
    db.session.commit()

    # Start AI Thread
    app_obj = current_app._get_current_object()
    threading.Thread(target=process_document_background, args=(app_obj, doc.id)).start()

    return jsonify({"status": "queued", "doc_id": doc.id, "file": original_name})
