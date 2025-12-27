import json
import boto3
import uuid
import base64
import datetime
from email import policy
from email.parser import BytesParser

# =========================
# AWS Clients
# =========================
s3 = boto3.client("s3", region_name="ap-south-1")
dynamodb = boto3.resource("dynamodb", region_name="ap-south-1")
ses = boto3.client("ses", region_name="ap-south-1")

# =========================
# Constants
# =========================
BUCKET_NAME = "sl-app-cv-submit-s3"
TABLE_NAME = "cvupload-sl-app"
ADMIN_EMAIL = "athilakshmiprem@gmail.com"

MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB
ALLOWED_CONTENT_TYPES = ["application/pdf"]

table = dynamodb.Table(TABLE_NAME)


def lambda_handler(event, context):
    try:
        # ---------------------------------
        # Decode multipart/form-data
        # ---------------------------------
        if "body" not in event:
            return response(400, "Invalid request")

        body = base64.b64decode(event["body"])
        headers = event.get("headers", {})
        content_type = headers.get("content-type") or headers.get("Content-Type")

        if not content_type:
            return response(400, "Missing Content-Type header")

        msg = BytesParser(policy=policy.default).parsebytes(
            b"Content-Type: " + content_type.encode() + b"\r\n\r\n" + body
        )

        full_name = None
        email_id = None
        file_bytes = None
        filename = None
        file_content_type = None

        for part in msg.iter_parts():
            if part.get_content_disposition() != "form-data":
                continue

            field_name = part.get_param("name", header="content-disposition")

            if field_name == "full_name":
                full_name = part.get_content().strip()

            elif field_name == "email":
                email_id = part.get_content().strip()

            elif field_name == "file":
                filename = part.get_filename()
                file_bytes = part.get_payload(decode=True)
                file_content_type = part.get_content_type()

        # ---------------------------------
        # Validation
        # ---------------------------------
        if not all([full_name, email_id, filename, file_bytes]):
            return response(400, "All fields (full_name, email, file) are required")

        if file_content_type not in ALLOWED_CONTENT_TYPES:
            return response(400, "Only PDF files are allowed")

        if len(file_bytes) > MAX_FILE_SIZE:
            return response(400, "File size must be less than 5MB")

        # ---------------------------------
        # Upload to S3
        # ---------------------------------
        cv_id = str(uuid.uuid4())
        s3_key = f"uploads/{cv_id}_{filename}"

        s3.put_object(
            Bucket=BUCKET_NAME,
            Key=s3_key,
            Body=file_bytes,
            ContentType=file_content_type
        )

        # ---------------------------------
        # Store metadata in DynamoDB
        # ---------------------------------
        uploaded_at = datetime.datetime.utcnow().isoformat()

        table.put_item(
            Item={
                "cv_id": cv_id,
                "full_name": full_name,
                "email": email_id,
                "file_name": filename,
                "s3_path": f"s3://{BUCKET_NAME}/{s3_key}",
                "uploaded_at": uploaded_at
            }
        )

        # ---------------------------------
        # Send Admin Email
        # ---------------------------------
        ses.send_email(
            Source=ADMIN_EMAIL,
            Destination={"ToAddresses": [ADMIN_EMAIL]},
            Message={
                "Subject": {"Data": "New CV Uploaded"},
                "Body": {
                    "Text": {
                        "Data": f"""
A new CV has been submitted.

Name: {full_name}
Email: {email_id}
File: {filename}
S3 Path: s3://{BUCKET_NAME}/{s3_key}
Uploaded At: {uploaded_at}
"""
                    }
                }
            }
        )

 
        return response(200, "CV uploaded successfully")

    except Exception as e:
        return response(500, f"Error: {str(e)}")


# =========================
# Common API Response
# =========================
def response(status_code, message):
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
            "Access-Control-Allow-Methods": "OPTIONS,POST"
        },
        "body": json.dumps({
            "message": message
        })
    }
