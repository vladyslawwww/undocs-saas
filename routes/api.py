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


def get_page_count(file_bytes, mime_type):
    """Returns the number of pages in a PDF or 1 for images."""
    if "pdf" in mime_type:
        import fitz

        try:
            with fitz.open(stream=file_bytes, filetype="pdf") as doc:
                return doc.page_count
        except Exception as e:
            print(f"PDF Page Count Error: {e}")
            return 1  # Fallback
    return 1  # Images are always 1 page


@api_bp.route("/ingest", methods=["POST"])
def ingest():
    raw_key = request.headers.get("X-API-Key")
    if not raw_key or not raw_key.startswith("und_"):
        return jsonify({"error": "Invalid API Key format"}), 401

    try:
        # Format: und_PROJECTID_SECRET
        parts = raw_key.split("_")
        project_id = int(parts[1])
        project = db.session.get(Project, project_id)

        if not project or not project.check_api_key(raw_key):
            return jsonify({"error": "Invalid API Key"}), 401
    except (ValueError, IndexError):
        return jsonify({"error": "Malformed API Key"}), 401

    # --- START: USAGE LIMIT LOGIC ---
    if project.pages_used >= project.page_limit:
        return jsonify(
            {
                "error": "Usage limit reached.",
                "message": f"You have used {project.pages_used}/{project.page_limit} documents. Please upgrade your plan.",
            }
        ), 402  # 402 Payment Required is the correct HTTP status code

    # --- END: USAGE LIMIT LOGIC ---

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

    # 1. Read bytes early to count pages
    file_bytes = file.read()
    mime_type = file.mimetype

    page_count = get_page_count(file_bytes, mime_type)

    # 2. Check if this specific upload exceeds remaining quota
    if project.pages_used + page_count > project.page_limit:
        return jsonify(
            {
                "error": "Quota exceeded",
                "message": f"This document has {page_count} pages, but you only have {project.page_limit - project.pages_used} pages left.",
            }
        ), 402

    # 3. Proceed with Upload to R2
    original_name = secure_filename(file.filename)
    storage_name = f"workspace_{project.id}/{uuid.uuid4().hex}_{original_name}"
    upload_file_to_r2(file_bytes, storage_name, mime_type)

    # 4. Create DB Entry
    doc = Document(
        filename=original_name,
        storage_filename=storage_name,
        schema_id=schema.id,
        status="QUEUED",
    )
    db.session.add(doc)

    # 5. Increment by ACTUAL PAGE COUNT
    project.pages_used += page_count
    db.session.commit()

    # 6. Publish to Serverless Queue
    success = publish_document_job(doc.id)

    if not success:
        # Fallback for local testing without QStash
        app_obj = current_app._get_current_object()
        # NOTE: We can't use threading here anymore as it won't have the file_bytes
        # This fallback needs to be adapted if used, but we're moving to QStash primarily.
        print("Warning: QStash is not configured. Job was not queued.")

    return jsonify({"status": "queued", "doc_id": doc.id, "file": original_name})
