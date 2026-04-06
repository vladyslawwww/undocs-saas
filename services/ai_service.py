import json

from models import DocSchema, Document, Project, db
from services.storage_service import get_file_bytes_from_r2

client = None


def get_gemini_client():
    """Lazily initializes and returns the Gemini client, creating it only once."""
    from google import genai

    global client
    if client is None:
        client = genai.Client()
    return client


def process_document_logic(app, doc_id):
    """Now only takes doc_id. Fetches bytes from R2 safely in the background."""
    with app.app_context():
        from google.genai import types

        doc = db.session.get(Document, doc_id)
        if not doc:
            return

        doc.status = "PROCESSING"
        db.session.commit()

        try:
            # 1. Fetch the client using helper function
            gemini = get_gemini_client()

            # 2. Fetch File Bytes from R2
            file_bytes = get_file_bytes_from_r2(doc.storage_filename)

            # 3. Infer Mime Type
            mime_type = "application/pdf"
            if doc.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                mime_type = "image/jpeg"

            schema = db.session.get(DocSchema, doc.schema_id)
            schema_json_str = json.dumps(schema.structure, indent=2)

            prompt = f"""
            You are a Data Extraction Engine. 
            
            TASK:
            Extract data from the document matching this JSON Schema:
            {schema_json_str}

            CRITICAL INSTRUCTIONS:
            1. The 'description' field is your PRIMARY instruction.
            2. Match the 'type' exactly.
            3. For 'date' fields, convert to ISO8601 (YYYY-MM-DD).
            4. Return ONLY valid JSON without markdown wrapping.
            """

            file_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)
            config = types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.0
            )

            response = gemini.models.generate_content(
                model="gemini-2.5-flash", contents=[file_part, prompt], config=config
            )

            result_json = response.text.strip()
            if result_json.startswith("```"):
                result_json = result_json.strip("```").removeprefix("json").strip()

            doc.extracted_data = json.loads(result_json)
            doc.status = "REVIEW_NEEDED"

        except Exception as e:
            print(f"Gemini API / Worker Error: {e}")
            doc.status = "ERROR"
            doc.extracted_data = {"error": str(e)}

        db.session.commit()


def trigger_webhook(doc):
    """Sends verified data to the user's receiver script"""
    import requests

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
            print(f"Webhook Delivery Failed: {e}")
