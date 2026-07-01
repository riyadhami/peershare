"""
peershare backend, AWS Lambda + S3 edition.

This replaces the raw-socket P2P transfer (p2p/file_sharer.py) with a
stateless design that fits a pay-per-request model: Lambda never touches
file bytes. It only ever hands out short-lived, signed S3 URLs:

  POST /upload         -> picks an invite code, returns a presigned PUT URL.
                           The browser PUTs the file straight to S3.
  GET  /download/{code} -> looks up the object under that code's S3 prefix,
                           302-redirects to a presigned GET URL.

The invite "code" doubles as the S3 key prefix (`{code}/{filename}`), so
there's no database mapping code -> file: the object's own key is the
mapping, which is what keeps this stateless across Lambda invocations
that may each run on a different underlying machine.
"""
import json
import os
import random

import boto3
from botocore.config import Config

BUCKET_NAME = os.environ["BUCKET_NAME"]

DYNAMIC_STARTING_PORT = 49152
DYNAMIC_ENDING_PORT = 65535

UPLOAD_URL_EXPIRES_IN = 300   # seconds the browser has to PUT the file
DOWNLOAD_URL_EXPIRES_IN = 300  # seconds the presigned download link is valid

s3 = boto3.client("s3", config=Config(signature_version="s3v4"))


def generate_code() -> int:
    """Same dynamic-port-shaped invite code as the socket version, just
    repurposed as an S3 key prefix instead of an actual port number."""
    return random.randint(DYNAMIC_STARTING_PORT, DYNAMIC_ENDING_PORT)


def _response(status: int, body, extra_headers: dict | None = None) -> dict:
    headers = {"Access-Control-Allow-Origin": "*", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    return {
        "statusCode": status,
        "headers": headers,
        "body": body if isinstance(body, str) else json.dumps(body),
    }


def _code_in_use(code: int) -> bool:
    listing = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{code}/", MaxKeys=1)
    return bool(listing.get("Contents"))


def _claim_code() -> int:
    # Same collision-retry idea as FileSharer.offer_file(), just checking
    # S3 instead of an in-memory dict, since Lambda has no shared memory
    # across invocations.
    for _ in range(5):
        code = generate_code()
        if not _code_in_use(code):
            return code
    raise RuntimeError("Could not allocate a free invite code, try again")


def handle_upload(event: dict) -> dict:
    try:
        payload = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"error": "Bad Request: body must be JSON"})

    raw_filename = (payload.get("filename") or "").strip()
    filename = os.path.basename(raw_filename) or "unnamed-file"
    content_type = payload.get("contentType") or "application/octet-stream"

    code = _claim_code()
    key = f"{code}/{filename}"

    upload_url = s3.generate_presigned_url(
        "put_object",
        Params={"Bucket": BUCKET_NAME, "Key": key, "ContentType": content_type},
        ExpiresIn=UPLOAD_URL_EXPIRES_IN,
    )

    return _response(200, {"port": code, "uploadUrl": upload_url})


def handle_download(code_str: str) -> dict:
    try:
        code = int(code_str)
    except ValueError:
        return _response(400, {"error": "Bad Request: Invalid port number"})

    listing = s3.list_objects_v2(Bucket=BUCKET_NAME, Prefix=f"{code}/", MaxKeys=1)
    contents = listing.get("Contents")
    if not contents:
        return _response(404, {"error": "Not Found: invite code is invalid or has expired"})

    key = contents[0]["Key"]
    filename = key.split("/", 1)[1] if "/" in key else key

    download_url = s3.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": BUCKET_NAME,
            "Key": key,
            "ResponseContentDisposition": f'attachment; filename="{filename}"',
        },
        ExpiresIn=DOWNLOAD_URL_EXPIRES_IN,
    )

    return {
        "statusCode": 302,
        "headers": {"Location": download_url, "Access-Control-Allow-Origin": "*"},
        "body": "",
    }


def lambda_handler(event: dict, context) -> dict:
    method = event.get("requestContext", {}).get("http", {}).get("method", "GET")
    path = event.get("rawPath", "/")

    if method == "OPTIONS":
        return _response(204, "")

    if method == "POST" and path == "/upload":
        return handle_upload(event)

    if method == "GET" and path.startswith("/download/"):
        return handle_download(path.rsplit("/", 1)[-1])

    return _response(404, {"error": "Not Found"})
