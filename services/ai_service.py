# services/ai_service.py
import json

from google import genai
from google.genai import types

from models import DocSchema, Document, Project, db

# The Client automatically picks up the GEMINI_API_KEY from your .env file
client = genai.Client()


def process_document_logic(app, doc_id, file_bytes, mime_type):
    with app.app_context():
        doc = db.session.get(Document, doc_id)
        if not doc:
            return

        doc.status = "PROCESSING"
        db.session.commit()

        try:
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

            # 1. Create a Part object using the file bytes directly
            file_part = types.Part.from_bytes(data=file_bytes, mime_type=mime_type)

            # 2. Configure the generation (strict JSON output)
            config = types.GenerateContentConfig(
                response_mime_type="application/json", temperature=0.0
            )

            # 3. Call the API using the new unified Client
            response = client.models.generate_content(
                model="gemini-2.5-flash", contents=[file_part, prompt], config=config
            )

            result_json = response.text.strip()

            # Clean up potential markdown formatting from Gemini
            if result_json.startswith("```"):
                result_json = result_json.strip("```").removeprefix("json").strip()

            doc.extracted_data = json.loads(result_json)
            doc.status = "REVIEW_NEEDED"

        except Exception as e:
            print(f"Gemini API Error: {e}")
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
