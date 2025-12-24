import os
import stripe
import random
import resend
from datetime import datetime, timezone, timedelta
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, firestore

# Initialize the Admin SDK once at the top level
initialize_app()

# Configuration constants
MAX_DEVICES = 2
OTP_EXPIRY_MINUTES = 5

@https_fn.on_request(
    region="europe-west1",
    secrets=["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def stripe_webhook(req: https_fn.Request) -> https_fn.Response:
    """
    Handle Stripe webhook events.
    When a purchase is complete, it creates/updates a user license in Firestore.
    """
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    if not stripe.api_key or not webhook_secret:
        return https_fn.Response("Missing required secrets", status=500)

    payload = req.get_data(as_text=True)
    sig_header = req.headers.get("Stripe-Signature")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, webhook_secret)
    except (ValueError, stripe.error.SignatureVerificationError):
        return https_fn.Response("Invalid payload or signature", status=400)

    # Logic for successful checkout
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email")

        if not customer_email:
            return https_fn.Response("No customer email in session", status=400)

        db = firestore.client()
        license_ref = db.collection("licenses").document(customer_email)

        # We set is_paid to True. We don't set hardware_id yet; 
        # that happens when the user first runs the CLI.
        license_ref.set({"is_paid": True}, merge=True)

        return https_fn.Response(f"License updated for {customer_email}", status=200)

    return https_fn.Response(f"Unhandled event: {event['type']}", status=200)


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
    Expects JSON: {"email": "user@example.com"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    if not email:
        return https_fn.Response("Missing email", status=400)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found for this email", status=404)

    license_data = doc.to_dict()
    if not license_data.get("is_paid"):
        return https_fn.Response("License not paid", status=403)

    # Generate 6-digit OTP
    otp_code = str(random.randint(100000, 999999))
    otp_expiry = datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)

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
            "from": "onboarding@resend.dev",
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
    Verify OTP and register the device.
    Expects JSON: {"email": "user@example.com", "otp": "123456", "device_uuid": "uuid", "device_nickname": "My Mac"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    otp = data.get("otp")
    device_uuid = data.get("device_uuid")
    device_nickname = data.get("device_nickname")

    if not all([email, otp, device_uuid, device_nickname]):
        return https_fn.Response("Missing required fields", status=400)

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
        return https_fn.Response(
            "OTP expired. Please request a new one.",
            status=400
        )
    if stored_otp != otp:
        return https_fn.Response("Invalid OTP", status=403)

    # Check device limit
    devices = license_data.get("devices", [])

    # Check if device already registered
    for device in devices:
        if device["uuid"] == device_uuid:
            return https_fn.Response("Device already registered", status=200)

    if len(devices) >= MAX_DEVICES:
        return https_fn.Response("Device limit reached", status=403)

    # Register device
    devices.append({
        "uuid": device_uuid,
        "nickname": device_nickname,
        "registered_at": datetime.utcnow().isoformat()
    })

    # Clear OTP and update devices
    doc_ref.update({
        "devices": devices,
        "otp_code": firestore.DELETE_FIELD,
        "otp_expiry": firestore.DELETE_FIELD
    })

    return https_fn.Response("Device registered successfully", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def validate_device(req: https_fn.Request) -> https_fn.Response:
    """
    Validate that a device is registered and licensed.
    Expects JSON: {"email": "user@example.com", "device_uuid": "uuid"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")

    if not email or not device_uuid:
        return https_fn.Response("Missing email or device_uuid", status=400)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()

    if not license_data.get("is_paid"):
        return https_fn.Response("License not paid", status=403)

    devices = license_data.get("devices", [])
    for device in devices:
        if device["uuid"] == device_uuid:
            return https_fn.Response("Valid", status=200)

    return https_fn.Response("Device not registered", status=403)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def replace_device(req: https_fn.Request) -> https_fn.Response:
    """
    Replace an old device with a new one.
    Expects JSON: {"email": "user@example.com", "old_device_uuid": "uuid", "new_device_uuid": "uuid", "new_device_nickname": "New Mac"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    old_device_uuid = data.get("old_device_uuid")
    new_device_uuid = data.get("new_device_uuid")
    new_device_nickname = data.get("new_device_nickname")

    if not all([email, old_device_uuid, new_device_uuid, new_device_nickname]):
        return https_fn.Response("Missing required fields", status=400)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()
    devices = license_data.get("devices", [])

    # Remove old device and add new device
    devices = [d for d in devices if d["uuid"] != old_device_uuid]
    devices.append({
        "uuid": new_device_uuid,
        "nickname": new_device_nickname,
        "registered_at": datetime.utcnow().isoformat()
    })

    doc_ref.update({"devices": devices})
    return https_fn.Response("Device replaced successfully", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def deregister_device(req: https_fn.Request) -> https_fn.Response:
    """
    Remove a device from the license.
    Expects JSON: {"email": "user@example.com", "device_uuid": "uuid"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")

    if not email or not device_uuid:
        return https_fn.Response("Missing email or device_uuid", status=400)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found", status=404)

    license_data = doc.to_dict()
    devices = license_data.get("devices", [])

    # Remove the device
    devices = [d for d in devices if d["uuid"] != device_uuid]

    doc_ref.update({"devices": devices})
    return https_fn.Response("Device deregistered successfully", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def verify_license(req: https_fn.Request) -> https_fn.Response:
    """
    Called by the Zest CLI to verify or link a machine to a license.
    Expects JSON: {"email": "user@example.com", "hardware_id": "unique_hw_string"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    hw_id = data.get("hardware_id")

    if not email or not hw_id:
        return https_fn.Response("Missing email or hardware_id", status=400)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found for this email", status=404)

    license_data = doc.to_dict()

    # If the license is paid but no hardware_id is linked yet, link it now.
    if not license_data.get("hardware_id"):
        doc_ref.update({"hardware_id": hw_id})
        return https_fn.Response("License successfully linked to this machine", status=200)

    # If a hardware_id is already linked, it must match the current machine.
    if license_data.get("hardware_id") == hw_id:
        return https_fn.Response("Verified", status=200)
    else:
        return https_fn.Response("License is already tied to a different machine", status=403)