# routes/api.py
import uuid

from flask import Blueprint, current_app, jsonify, request
from werkzeug.utils import secure_filename

from models import DocSchema, Document, Project, db
from services.queue_service import publish_document_job
from services.storage_service import upload_file_to_r2

api_bp = Blueprint("api", __name__, url_prefix="/api")

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


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

    if not file or not allowed_file(file.filename):
        return jsonify(
            {"error": "Invalid file type. Only PDF and Images allowed."}
        ), 400

    schema = DocSchema.query.filter_by(project_id=project.id, name=schema_name).first()
    if not schema:
        return jsonify({"error": f"Schema '{schema_name}' not found"}), 404

    # 1. Generate Secure Filename & Read Bytes
    original_name = secure_filename(file.filename)
    storage_name = f"workspace_{project.id}/{uuid.uuid4().hex}_{original_name}"

    file_bytes = file.read()
    mime_type = file.mimetype

    # 2. Upload to S3/Cloudflare R2
    upload_file_to_r2(file_bytes, storage_name, mime_type)

    # 3. Create DB Entry
    doc = Document(
        filename=original_name,
        storage_filename=storage_name,
        schema_id=schema.id,
        status="QUEUED",
    )
    db.session.add(doc)
    db.session.commit()

    # 4. Publish to Serverless Queue
    success = publish_document_job(doc.id)

    if not success:
        # Fallback for local testing without QStash
        import threading

        from services.ai_service import process_document_logic

        app_obj = current_app._get_current_object()
        threading.Thread(target=process_document_logic, args=(app_obj, doc.id)).start()

    return jsonify({"status": "queued", "doc_id": doc.id, "file": original_name})
