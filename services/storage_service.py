# services/storage_service.py
import os

import boto3
from botocore.config import Config


def get_s3_client():
    """Connects to Cloudflare R2 or AWS S3 based on env vars"""
    return boto3.client(
        "s3",
        endpoint_url=os.getenv(
            "R2_ENDPOINT_URL"
        ),  # e.g. https://<ID>.r2.cloudflarestorage.com
        aws_access_key_id=os.getenv("R2_ACCESS_KEY"),
        aws_secret_access_key=os.getenv("R2_SECRET_KEY"),
        config=Config(signature_version="s3v4"),
        region_name="auto",
    )


def upload_file_to_r2(file_bytes, filename, content_type):
    s3 = get_s3_client()
    bucket = os.getenv("R2_BUCKET_NAME", "undocs-storage")

    s3.put_object(
        Bucket=bucket, Key=filename, Body=file_bytes, ContentType=content_type
    )
    return filename


def get_file_url(filename):
    """Generates a secure, temporary URL to view the file (Valid for 1 hour)"""
    s3 = get_s3_client()
    bucket = os.getenv("R2_BUCKET_NAME", "undocs-storage")
    return s3.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": filename}, ExpiresIn=3600
    )


def get_file_bytes_from_r2(filename):
    """Downloads file bytes directly into memory for AI processing"""
    s3 = get_s3_client()
    bucket = os.getenv("R2_BUCKET_NAME", "undocs-storage")
    response = s3.get_object(Bucket=bucket, Key=filename)
    return response["Body"].read()
