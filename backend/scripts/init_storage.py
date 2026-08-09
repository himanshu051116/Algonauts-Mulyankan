"""Initialise MinIO bucket CORS policy for browser-based signed uploads.

Called as part of the migration/init container startup sequence.
Safe to run repeatedly — idempotent via put_bucket_cors overwrite.
"""

import os

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

BUCKET = os.environ["STORAGE_BUCKET"]
ENDPOINT = os.environ["STORAGE_ENDPOINT"]
ACCESS_KEY = os.environ["STORAGE_ACCESS_KEY"]
SECRET_KEY = os.environ["STORAGE_SECRET_KEY"]

CORS_ORIGINS_ENV = os.environ.get("CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000")
ALLOWED_ORIGINS = [o.strip() for o in CORS_ORIGINS_ENV.split(",") if o.strip()]


def init_storage():
    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT,
        aws_access_key_id=ACCESS_KEY,
        aws_secret_access_key=SECRET_KEY,
        region_name="us-east-1",
        config=Config(signature_version="s3v4"),
    )

    try:
        client.head_bucket(Bucket=BUCKET)
    except ClientError:
        print(f"  Creating bucket '{BUCKET}'...")
        client.create_bucket(Bucket=BUCKET)

    client.put_bucket_cors(
        Bucket=BUCKET,
        CORSConfiguration={
            "CORSRules": [
                {
                    "AllowedOrigins": ALLOWED_ORIGINS,
                    "AllowedMethods": ["PUT", "GET", "HEAD"],
                    "AllowedHeaders": ["*"],
                    "ExposeHeaders": ["ETag"],
                    "MaxAgeSeconds": 3600,
                }
            ]
        },
    )
    print(f"  CORS configured for bucket '{BUCKET}'.")
    print(f"  Allowed origins: {', '.join(ALLOWED_ORIGINS)}")


if __name__ == "__main__":
    init_storage()
