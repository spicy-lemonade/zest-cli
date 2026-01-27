"""
Version checking cloud function for Zest CLI.
"""

import json
from firebase_functions import https_fn, options
from firebase_admin import firestore

from config import VALID_PRODUCTS, MODEL_FILES, GCS_BUCKET, SERVICE_ACCOUNT_EMAIL


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["GET", "POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def check_version(req: https_fn.Request) -> https_fn.Response:
    """
    Check for available updates.
    Returns the latest versions of CLI and models.

    GET or POST with optional JSON: {
        "current_version": "1.0.0",
        "current_model_version": "1.0.0",
        "product": "lite", "hot", or "extra_spicy"
    }

    Response includes:
    - latest_cli_version: Latest CLI version available
    - latest_model_version: Latest model version for the product
    - cli_update_available: Boolean indicating if CLI update is available
    - model_update_available: Boolean indicating if model update is available
    - update_message: Optional message to display to user
    - update_url: URL to download CLI update
    - model_download_url: Direct URL to download updated model
    - model_filename: Filename of the model
    - model_size_bytes: Size of the model file (for progress display)
    """
    current_version = None
    current_model_version = None
    product = "lite"

    if req.method == "POST":
        try:
            data = req.get_json()
            current_version = data.get("current_version")
            current_model_version = data.get("current_model_version")
            product = data.get("product", "lite")
        except Exception:
            pass

    if product not in VALID_PRODUCTS:
        product = "lite"

    db = firestore.client()

    version_ref = db.collection("versions").document("current")
    version_doc = version_ref.get()

    model_filename = MODEL_FILES.get(product, MODEL_FILES["lite"])
    model_download_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{model_filename}"

    if not version_doc.exists:
        return https_fn.Response(json.dumps({
            "latest_cli_version": "1.0.0",
            "latest_model_version": "1.0.0",
            "cli_update_available": False,
            "model_update_available": False,
            "update_message": None,
            "update_url": "https://zestcli.com",
            "model_download_url": model_download_url,
            "model_filename": model_filename,
            "model_size_bytes": 0
        }), status=200, content_type="application/json")

    version_data = version_doc.to_dict()
    latest_cli = version_data.get("cli_version", "1.0.0")
    latest_model = version_data.get(f"{product}_model_version", "1.0.0")
    model_size = version_data.get(f"{product}_model_size", 0)
    update_message = version_data.get("update_message")
    update_url = version_data.get("update_url", "https://zestcli.com")

    cli_update_available = False
    if current_version:
        try:
            current_parts = [int(x) for x in current_version.split(".")]
            latest_parts = [int(x) for x in latest_cli.split(".")]
            cli_update_available = latest_parts > current_parts
        except (ValueError, AttributeError):
            pass

    model_update_available = False
    if current_model_version:
        try:
            current_parts = [int(x) for x in current_model_version.split(".")]
            latest_parts = [int(x) for x in latest_model.split(".")]
            model_update_available = latest_parts > current_parts
        except (ValueError, AttributeError):
            pass

    return https_fn.Response(json.dumps({
        "latest_cli_version": latest_cli,
        "latest_model_version": latest_model,
        "cli_update_available": cli_update_available,
        "model_update_available": model_update_available,
        "update_message": update_message,
        "update_url": update_url,
        "model_download_url": model_download_url,
        "model_filename": model_filename,
        "model_size_bytes": model_size
    }), status=200, content_type="application/json")
