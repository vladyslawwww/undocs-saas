import json
import os

import requests
import vertexai
from vertexai.generative_models import GenerativeModel, Part

from models import DocSchema, Document, Project, db

# Initialize Vertex AI
project_id = os.getenv("GOOGLE_CLOUD_PROJECT")
location = os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1")
vertexai.init(project=project_id, location=location)


def process_document_background(app, doc_id):
    with app.app_context():
        doc = Document.query.get(doc_id)
        if not doc:
            return

        doc.status = "PROCESSING"
        db.session.commit()

        try:
            schema = DocSchema.query.get(doc.schema_id)
            schema_json_str = json.dumps(schema.structure, indent=2)

            prompt = f"""
            You are a Data Extraction Engine. 
            
            TASK:
            Extract data from the document matching this JSON Schema:
            {schema_json_str}

            CRITICAL INSTRUCTIONS:
            1. The 'description' field in the schema is your PRIMARY instruction for what to find.
            2. Match the 'type' exactly (string, number, boolean, date, array).
            3. For 'date' fields, convert to ISO8601 (YYYY-MM-DD).
            4. For 'number' fields, remove currency symbols and commas.
            5. Return ONLY valid JSON.
            """

            model = GenerativeModel("gemini-2.5-flash")

            file_path = os.path.join("static/uploads", doc.storage_filename)

            with open(file_path, "rb") as f:
                file_bytes = f.read()

            mime_type = "application/pdf"
            if doc.filename.lower().endswith((".png", ".jpg", ".jpeg")):
                mime_type = "image/jpeg"

            response = model.generate_content(
                [Part.from_data(data=file_bytes, mime_type=mime_type), prompt],
                generation_config={
                    "response_mime_type": "application/json",
                    "temperature": 0.0,
                },
            )

            result_json = response.text.strip()
            if result_json.startswith("```json"):
                result_json = result_json.split("```json")[1].split("```")[0]

            doc.extracted_data = json.loads(result_json)
            doc.status = "REVIEW_NEEDED"

        except Exception as e:
            print(f"Vertex AI Error: {e}")
            doc.status = "ERROR"
            doc.extracted_data = {"error": str(e)}

        db.session.commit()


def trigger_webhook(doc):
    """Sends verified data to the user's receiver script"""
    schema = DocSchema.query.get(doc.schema_id)
    project = Project.query.get(schema.project_id)

    if project.webhook_url:
        try:
            requests.post(
                project.webhook_url,
                json={
                    "document_id": doc.id,
                    "filename": doc.filename,
                    "final_data": doc.extracted_data,
                    "status": "COMPLETED",
                    "provider": "Google Vertex AI (Gemini 2.5 Flash)",
                },
                timeout=5,
            )
        except Exception as e:
            print(f"Webhook Delivery Failed: {e}")
