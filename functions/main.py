import os
import hmac
import hashlib
import json
import random
import uuid
import resend
from datetime import datetime, timezone, timedelta
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, firestore

# Initialize the Admin SDK once at the top level
initialize_app()

# Configuration constants
MAX_DEVICES_PER_PRODUCT = 2
OTP_EXPIRY_MINUTES = 10
VALID_PRODUCTS = ["fp16", "q5"]


def get_product_fields(product: str) -> tuple:
    """Return field names for a given product type."""
    return (f"{product}_is_paid", f"{product}_devices", f"{product}_polar_order_id")

@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN", "POLAR_WEBHOOK_SECRET"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def polar_webhook(req: https_fn.Request) -> https_fn.Response:
    """
    Handle Polar.sh webhook events.
    When a purchase is complete, it creates/updates a user license in Firestore.

    Note: POLAR_SUCCESS_URL is configured in the Polar dashboard, not needed here.
    """
    webhook_secret = os.environ.get("POLAR_WEBHOOK_SECRET")
    if not webhook_secret:
        return https_fn.Response("Missing webhook secret", status=500)

    payload = req.get_data(as_text=True)
    sig_header = req.headers.get("X-Polar-Signature")

    if not sig_header:
        return https_fn.Response("Missing signature header", status=400)

    # Verify webhook signature using HMAC-SHA256
    expected_signature = hmac.new(
        webhook_secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(sig_header, expected_signature):
        return https_fn.Response("Invalid signature", status=400)

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return https_fn.Response("Invalid JSON payload", status=400)

    # Logic for successful order
    # Polar sends "order.paid" when payment is confirmed
    if event.get("type") == "order.paid":
        order = event.get("data", {})
        customer = order.get("customer", {})
        customer_email = customer.get("email")

        if not customer_email:
            return https_fn.Response("No customer email in order", status=400)

        # Determine product type from product name
        # Expected product names: "Zest CLI FP16" or "Zest CLI Q5" (or similar)
        product = order.get("product", {})
        product_name = product.get("name", "").lower()

        if "fp16" in product_name or "fp" in product_name:
            product_type = "fp16"
        elif "q5" in product_name or "quantized" in product_name:
            product_type = "q5"
        else:
            # Default to q5 if unclear
            product_type = "q5"

        paid_field, devices_field, order_field = get_product_fields(product_type)

        db = firestore.client()
        license_ref = db.collection("licenses").document(customer_email)

        # Check if license already exists to preserve user_id
        existing_doc = license_ref.get()
        if existing_doc.exists:
            existing_data = existing_doc.to_dict()
            zest_user_id = existing_data.get("zest_user_id", str(uuid.uuid4()))
        else:
            zest_user_id = str(uuid.uuid4())

        now = datetime.now(timezone.utc)
        license_ref.set({
            "zest_user_id": zest_user_id,
            "email": customer_email,
            "polar_customer_id": order.get("customer_id"),
            "polar_user_id": order.get("user_id"),
            "updated_at": now.isoformat(),
            "updated_at_unix": int(now.timestamp()),
            paid_field: True,
            order_field: order.get("id")
        }, merge=True)

        return https_fn.Response(
            f"License for {product_type} updated for {customer_email}",
            status=200
        )

    return https_fn.Response(f"Unhandled event: {event.get('type')}", status=200)


@https_fn.on_request(
    region="europe-west1",
    secrets=["RESEND_API_KEY"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def send_otp(req: https_fn.Request) -> https_fn.Response:
    """
    Generate a 6-digit OTP and send it to the user's email via Resend.
    Expects JSON: {"email": "user@example.com", "product": "fp16" or "q5"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    product = data.get("product", "q5")

    if not email:
        return https_fn.Response("Missing email", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    paid_field, _, _ = get_product_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found for this email", status=404)

    license_data = doc.to_dict()
    if not license_data.get(paid_field):
        return https_fn.Response(f"No {product} license found for this email", status=403)

    # Generate 6-digit OTP
    otp_code = str(random.randint(100000, 999999))
    otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)
    
    # Save OTP to Firestore
    doc_ref.update({
        "otp_code": otp_code,
        "otp_expiry": otp_expiry
    })

    # Send email via Resend
    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        return https_fn.Response("Missing Resend API key", status=500)

    resend.api_key = resend_api_key

    try:
        resend.Emails.send({
            "from": "info@zestcli.com",
            "to": email,
            "subject": "Your Zest CLI Verification Code",
            "html": f"""
                <h2>Your Zest CLI Verification Code</h2>
                <p>Use this code to activate your device:</p>
                <h1 style="font-size: 32px; letter-spacing: 4px; font-family: monospace;">{otp_code}</h1>
                <p>This code will expire in {OTP_EXPIRY_MINUTES} minutes.</p>
                <p>If you did not request this code, please ignore this email.</p>
            """
        })
        return https_fn.Response("OTP sent successfully", status=200)
    except Exception as e:
        return https_fn.Response(f"Failed to send email: {str(e)}", status=500)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def verify_otp_and_register(req: https_fn.Request) -> https_fn.Response:
    """
    Verify OTP and register the device for a specific product.
    Expects JSON: {"email": "...", "otp": "123456", "device_uuid": "uuid",
                   "device_nickname": "My Mac", "product": "fp16" or "q5"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    otp = data.get("otp")
    device_uuid = data.get("device_uuid")
    device_nickname = data.get("device_nickname")
    product = data.get("product", "q5")

    if not all([email, otp, device_uuid, device_nickname]):
        return https_fn.Response("Missing required fields", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    paid_field, devices_field, _ = get_product_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()

    # Verify OTP
    stored_otp = license_data.get("otp_code")
    otp_expiry = license_data.get("otp_expiry")

    if not stored_otp or not otp_expiry:
        return https_fn.Response("No OTP found. Please request a new one.", status=400)

    if datetime.now(timezone.utc) > otp_expiry:
        return https_fn.Response("OTP expired. Please request a new one.", status=400)

    if stored_otp != otp:
        return https_fn.Response("Invalid OTP", status=403)

    # Check if user has license for this product
    if not license_data.get(paid_field):
        return https_fn.Response(f"No {product} license found", status=403)

    # Check device limit for this product
    devices = license_data.get(devices_field, [])

    # Check if device already registered for this product
    for device in devices:
        if device["uuid"] == device_uuid:
            return https_fn.Response(f"Device already registered for {product}", status=200)

    if len(devices) >= MAX_DEVICES_PER_PRODUCT:
        device_list = [
            {"uuid": d["uuid"], "nickname": d.get("nickname", "Unknown device")}
            for d in devices
        ]
        return https_fn.Response(
            json.dumps({
                "error": "device_limit_reached",
                "message": f"Device limit reached ({len(devices)}/{MAX_DEVICES_PER_PRODUCT})",
                "devices": device_list
            }),
            status=403,
            content_type="application/json"
        )

    # Register device
    now = datetime.now(timezone.utc)
    devices.append({
        "uuid": device_uuid,
        "nickname": device_nickname,
        "registered_at": now.isoformat(),
        "registered_at_unix": int(now.timestamp()),
        "last_validated": now.isoformat(),
        "last_validated_unix": int(now.timestamp())
    })

    # Clear OTP and update devices
    doc_ref.update({
        devices_field: devices,
        "otp_code": firestore.DELETE_FIELD,
        "otp_expiry": firestore.DELETE_FIELD
    })

    return https_fn.Response(f"Device registered for {product}", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def validate_device(req: https_fn.Request) -> https_fn.Response:
    """
    Validate that a device is registered and licensed for a specific product.
    Expects JSON: {"email": "...", "device_uuid": "uuid", "product": "fp16" or "q5"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")
    product = data.get("product", "q5")

    if not email or not device_uuid:
        return https_fn.Response("Missing email or device_uuid", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    paid_field, devices_field, _ = get_product_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()

    if not license_data.get(paid_field):
        return https_fn.Response(f"No {product} license found", status=403)

    devices = license_data.get(devices_field, [])
    for device in devices:
        if device["uuid"] == device_uuid:
            return https_fn.Response("Valid", status=200)

    return https_fn.Response(f"Device not registered for {product}", status=403)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def replace_device(req: https_fn.Request) -> https_fn.Response:
    """
    Replace an old device with a new one for a specific product.
    Expects JSON: {"email": "...", "old_device_uuid": "uuid", "new_device_uuid": "uuid",
                   "new_device_nickname": "New Mac", "product": "fp16" or "q5"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    old_device_uuid = data.get("old_device_uuid")
    new_device_uuid = data.get("new_device_uuid")
    new_device_nickname = data.get("new_device_nickname")
    product = data.get("product", "q5")

    if not all([email, old_device_uuid, new_device_uuid, new_device_nickname]):
        return https_fn.Response("Missing required fields", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    _, devices_field, _ = get_product_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()
    devices = license_data.get(devices_field, [])

    # Remove old device and add new device
    devices = [d for d in devices if d["uuid"] != old_device_uuid]
    now = datetime.now(timezone.utc)
    devices.append({
        "uuid": new_device_uuid,
        "nickname": new_device_nickname,
        "registered_at": now.isoformat(),
        "registered_at_unix": int(now.timestamp()),
        "last_validated": now.isoformat(),
        "last_validated_unix": int(now.timestamp())
    })

    doc_ref.update({devices_field: devices})
    return https_fn.Response(f"Device replaced for {product}", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def deregister_device(req: https_fn.Request) -> https_fn.Response:
    """
    Remove a device from the license for a specific product.
    Expects JSON: {"email": "...", "device_uuid": "uuid", "product": "fp16" or "q5"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")
    product = data.get("product", "q5")

    if not email or not device_uuid:
        return https_fn.Response("Missing email or device_uuid", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    _, devices_field, _ = get_product_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()
    devices = license_data.get(devices_field, [])

    # Remove the device
    devices = [d for d in devices if d["uuid"] != device_uuid]

    doc_ref.update({devices_field: devices})
    return https_fn.Response(f"Device deregistered from {product}", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def license_heartbeat(req: https_fn.Request) -> https_fn.Response:
    """
    Biweekly license validation ping from the CLI.
    Updates last_validated timestamp for the device for a specific product.
    Expects JSON: {"email": "...", "device_uuid": "uuid", "product": "fp16" or "q5"}

    The CLI should call this every 2 weeks. If the ping fails due to network
    issues, the CLI can continue operating using cached validation.
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")
    product = data.get("product", "q5")

    if not email or not device_uuid:
        return https_fn.Response("Missing email or device_uuid", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    paid_field, devices_field, _ = get_product_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()

    if not license_data.get(paid_field):
        return https_fn.Response(f"No {product} license found", status=403)

    devices = license_data.get(devices_field, [])
    device_found = False
    now = datetime.now(timezone.utc)

    for i, device in enumerate(devices):
        if device["uuid"] == device_uuid:
            device_found = True
            devices[i]["last_validated"] = now.isoformat()
            devices[i]["last_validated_unix"] = int(now.timestamp())
            break

    if not device_found:
        return https_fn.Response(f"Device not registered for {product}", status=403)

    doc_ref.update({devices_field: devices})
    return https_fn.Response(json.dumps({
        "status": "valid",
        "product": product,
        "validated_at": now.isoformat(),
        "validated_at_unix": int(now.timestamp())
    }), status=200, content_type="application/json")


# Model file configuration
MODEL_FILES = {
    "fp16": "qwen3_4b_fp16.gguf",
    "q5": "qwen3_4b_Q5_K_M.gguf"
}
GCS_BUCKET = "nlcli-models"


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["GET", "POST"],
    ),
)
def check_version(req: https_fn.Request) -> https_fn.Response:
    """
    Check for available updates.
    Returns the latest versions of CLI and models.

    GET or POST with optional JSON: {
        "current_version": "1.0.0",
        "current_model_version": "1.0.0",
        "product": "fp16" or "q5"
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
    product = "q5"

    if req.method == "POST":
        try:
            data = req.get_json()
            current_version = data.get("current_version")
            current_model_version = data.get("current_model_version")
            product = data.get("product", "q5")
        except Exception:
            pass

    if product not in VALID_PRODUCTS:
        product = "q5"

    db = firestore.client()

    # Get version info from Firestore
    # Document structure: versions/current with fields:
    # cli_version, fp16_model_version, q5_model_version,
    # fp16_model_size, q5_model_size, update_message, update_url
    version_ref = db.collection("versions").document("current")
    version_doc = version_ref.get()

    model_filename = MODEL_FILES.get(product, MODEL_FILES["q5"])
    model_download_url = f"https://storage.googleapis.com/{GCS_BUCKET}/{model_filename}"

    if not version_doc.exists:
        # If no version document exists, return defaults
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

    # Determine if CLI update is available
    cli_update_available = False
    if current_version:
        try:
            current_parts = [int(x) for x in current_version.split(".")]
            latest_parts = [int(x) for x in latest_cli.split(".")]
            cli_update_available = latest_parts > current_parts
        except (ValueError, AttributeError):
            pass

    # Determine if model update is available
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
