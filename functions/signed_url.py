"""
Signed URL generation for model downloads.
Verifies license/trial status before issuing a time-limited download URL.
"""

import json
from datetime import timedelta

from firebase_functions import https_fn, options
from firebase_admin import firestore
from google.cloud import storage
from google.auth import default
from google.auth.transport import requests as auth_requests

from config import MODEL_FILE, GCS_BUCKET, SERVICE_ACCOUNT_EMAIL
from helpers import get_trial_status

SIGNED_URL_EXPIRY_HOURS = 4


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def get_model_download_url(req: https_fn.Request) -> https_fn.Response:
    """
    Generate a signed URL for model download after verifying license or trial.

    Expects JSON: {"email": "...", "device_id": "..."}
    Returns: {"download_url": "...", "model_size_bytes": ...}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_id = data.get("device_id")

    if not email or not device_id:
        return https_fn.Response("Missing email or device_id", status=400)

    db = firestore.client()
    license_ref = db.collection("licenses").document(email)
    license_doc = license_ref.get()

    if not license_doc.exists:
        return https_fn.Response("No license found", status=403)

    license_data = license_doc.to_dict()
    trial_status = get_trial_status(license_data)

    if trial_status["status"] not in ("paid", "trial_active"):
        return https_fn.Response("License expired or not found", status=403)

    if not MODEL_FILE or not GCS_BUCKET:
        return https_fn.Response("Model configuration error", status=500)

    credentials, project = default()
    credentials.refresh(auth_requests.Request())

    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET)
    blob = bucket.get_blob(MODEL_FILE)

    if blob is None:
        return https_fn.Response("Model file not found", status=500)

    url = blob.generate_signed_url(
        version="v4",
        expiration=timedelta(hours=SIGNED_URL_EXPIRY_HOURS),
        method="GET",
        service_account_email=credentials.service_account_email,
        access_token=credentials.token,
    )

    return https_fn.Response(
        json.dumps({"download_url": url, "model_size_bytes": blob.size}),
        status=200,
        content_type="application/json",
    )
