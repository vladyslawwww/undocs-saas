import json
import os
import threading

from models import DocSchema, Document, Project, db
from services.storage_service import get_file_bytes_from_r2

# --- CONCURRENCY CONTROL ---
# Render Free Tier only has 512MB. We limit to 2 concurrent AI jobs.
active_jobs_lock = threading.Lock()
active_jobs_count = 0
MAX_CONCURRENT_JOBS = 2

# --- LAZY CLIENT INITIALIZATION ---
client = None


def get_gemini_client():
    """Lazily initializes the Google GenAI client only when needed."""
    global client
    if client is None:
        from google import genai  # Lazy import to save RAM on startup

        client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return client


def process_document_logic(app, doc_id):
    """
    The core AI extraction engine.
    Downloads from R2, processes via Gemini 2.5 Flash, and updates DB.
    """
    global active_jobs_count

    # 1. Thread-Safe Concurrency Check
    with active_jobs_lock:
        if active_jobs_count >= MAX_CONCURRENT_JOBS:
            print(
                f"⚠️ Max AI concurrency reached ({MAX_CONCURRENT_JOBS}). Skipping doc {doc_id}."
            )
            # Note: Because this is called via QStash, if we return without success,
            # we should ideally return a 429 in the route, but since this is a thread,
            # we rely on the next QStash retry if the server OOMs or restarts.
            return
        active_jobs_count += 1

    try:
        with app.app_context():
            doc = db.session.get(Document, doc_id)
            if not doc:
                return

            doc.status = "PROCESSING"
            db.session.commit()

            try:
                # 2. Fetch File Bytes from Cloudflare R2
                file_bytes = get_file_bytes_from_r2(doc.storage_filename)

                # 3. Infer Mime Type
                mime_type = "application/pdf"
                if doc.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                    mime_type = "image/jpeg"

                # 4. Prepare AI Prompt from Schema
                schema = db.session.get(DocSchema, doc.schema_id)
                schema_json_str = json.dumps(schema.structure, indent=2)

                prompt = f"""
                You are a Data Extraction Engine. 
                
                TASK:
                Extract data from the document matching this JSON Schema:
                {schema_json_str}

                CRITICAL INSTRUCTIONS:
                1. The 'description' field is your PRIMARY instruction for each field.
                2. Match the 'type' exactly (string, number, boolean, date, array).
                3. For 'date' fields, convert to ISO8601 (YYYY-MM-DD).
                4. For 'number' fields, remove currency symbols and commas.
                5. Return ONLY valid JSON. No markdown formatting.
                """

                # 5. Execute AI Request (Lazy Loaded SDK)
                from google.genai import types

                gemini = get_gemini_client()

                file_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

                config = types.GenerateContentConfig(
                    response_mime_type="application/json", temperature=0.0
                )

                response = gemini.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=[file_part, prompt],
                    config=config,
                )

                # 6. Parse and Clean Response
                result_json = response.text.strip()
                if result_json.startswith("```"):
                    # Remove markdown code blocks if Gemini accidentally includes them
                    result_json = result_json.strip("```").removeprefix("json").strip()

                doc.extracted_data = json.loads(result_json)
                doc.status = "REVIEW_NEEDED"

            except Exception as e:
                print(f"❌ AI Worker Error for doc {doc_id}: {str(e)}")
                doc.status = "ERROR"
                doc.extracted_data = {"error": str(e)}

            db.session.commit()

    finally:
        # 7. Always release the slot, even if it crashed
        with active_jobs_lock:
            active_jobs_count -= 1
            print(
                f"ℹ️ AI Job finished. Active slots: {MAX_CONCURRENT_JOBS - active_jobs_count}"
            )


def trigger_webhook(doc):
    """Sends verified data to the user's receiver script"""
    import requests  # Lazy import

    schema = db.session.get(DocSchema, doc.schema_id)
    project = db.session.get(Project, schema.project_id)

    if project.webhook_url:
        try:
            requests.post(
                project.webhook_url,
                json={
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "final_data": doc.extracted_data,
                    "status": "COMPLETED",
                    "provider": "Google AI Studio (Gemini 2.5 Flash)",
                },
                timeout=5,
            )
        except Exception as e:
            print(f"⚠️ Webhook Delivery Failed: {e}")
