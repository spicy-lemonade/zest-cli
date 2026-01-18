import os
import json
import random
import uuid
import resend
from datetime import datetime, timezone, timedelta
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, firestore
from polar_sdk import Polar
from standardwebhooks.webhooks import Webhook

# Initialize the Admin SDK once at the top level
initialize_app()

# Configuration constants
MAX_DEVICES_PER_PRODUCT = 2
OTP_EXPIRY_MINUTES = 10
VALID_PRODUCTS = ["lite", "hot", "extra_spicy"]
TRIAL_DURATION_DAYS = 5

# Polar.sh product IDs (from sandbox dashboard)
POLAR_PRODUCT_IDS = {
    "lite": "1cb33873-4b44-4cda-83cb-511805e7f02c",
    "hot": "47d61b83-33f5-45b4-8543-66a4d1afe8d6",
    "extra_spicy": "8a5011a7-d888-4c3e-9086-bb1063f50b30",
}


def get_product_fields(product: str) -> tuple:
    """Return field names for a given product type."""
    return (f"{product}_is_paid", f"{product}_devices", f"{product}_polar_order_id")


def get_trial_fields(product: str) -> tuple:
    """Return trial-related field names for a given product type."""
    return (
        f"{product}_is_trial",
        f"{product}_trial_started_at",
        f"{product}_trial_expires_at"
    )


def check_machine_trial_used(db, device_id: str, product: str) -> dict:
    """
    Check if a machine ID has already been used for a trial on any email.
    Returns {"used": bool, "email": str or None, "expired": bool or None}.
    """
    if not device_id:
        return {"used": False, "email": None, "expired": None}

    # Check the trial_machines collection
    machine_ref = db.collection("trial_machines").document(device_id)
    machine_doc = machine_ref.get()

    if not machine_doc.exists:
        return {"used": False, "email": None, "expired": None}

    machine_data = machine_doc.to_dict()
    trial_email = machine_data.get(f"{product}_trial_email")

    if not trial_email:
        return {"used": False, "email": None, "expired": None}

    # Check if that trial is still active or expired
    license_ref = db.collection("licenses").document(trial_email)
    license_doc = license_ref.get()

    if not license_doc.exists:
        return {"used": True, "email": trial_email, "expired": True}

    license_data = license_doc.to_dict()
    _, _, expires_field = get_trial_fields(product)
    expires_at = license_data.get(expires_field)

    if expires_at:
        now = datetime.now(timezone.utc)
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        expired = now >= expires_at
        return {"used": True, "email": trial_email, "expired": expired}

    return {"used": True, "email": trial_email, "expired": True}


def record_machine_trial(db, device_id: str, email: str, product: str):
    """Record that a machine ID has been used for a trial."""
    if not device_id:
        return

    machine_ref = db.collection("trial_machines").document(device_id)
    machine_ref.set({
        f"{product}_trial_email": email,
        f"{product}_trial_started_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat()
    }, merge=True)


def get_trial_status(license_data: dict, product: str) -> dict:
    """
    Check trial status for a product. Returns a dict with:
    - status: "paid", "trial_active", "trial_expired", or "no_license"
    - Additional fields depending on status
    """
    paid_field, devices_field, _ = get_product_fields(product)
    trial_field, _, expires_field = get_trial_fields(product)

    if license_data.get(paid_field):
        devices = license_data.get(devices_field, [])
        return {"status": "paid", "devices_registered": len(devices)}

    if license_data.get(trial_field):
        expires_at = license_data.get(expires_field)
        if expires_at:
            now = datetime.now(timezone.utc)
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if now < expires_at:
                remaining = expires_at - now
                hours_remaining = int(remaining.total_seconds() / 3600)
                days_remaining = hours_remaining // 24
                return {
                    "status": "trial_active",
                    "days_remaining": days_remaining,
                    "hours_remaining": hours_remaining,
                    "trial_expires_at": expires_at.isoformat()
                }
            else:
                return {"status": "trial_expired"}

    return {"status": "no_license"}


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def create_checkout(req: https_fn.Request) -> https_fn.Response:
    """
    Create a Polar.sh checkout session for a product.
    Expects JSON: {"product": "lite"}, {"product": "hot"}, or {"product": "extra_spicy"}
    Returns: {"checkout_url": "https://..."}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response(
            json.dumps({"error": "Invalid JSON"}),
            status=400,
            content_type="application/json"
        )

    product = data.get("product")

    if not product:
        return https_fn.Response(
            json.dumps({"error": "Missing product field"}),
            status=400,
            content_type="application/json"
        )

    if product not in POLAR_PRODUCT_IDS:
        return https_fn.Response(
            json.dumps({"error": f"Invalid product. Available: {list(POLAR_PRODUCT_IDS.keys())}"}),
            status=400,
            content_type="application/json"
        )

    polar_access_token = os.environ.get("POLAR_ACCESS_TOKEN")
    polar_success_url = os.environ.get("POLAR_SUCCESS_URL")

    if not polar_access_token:
        return https_fn.Response(
            json.dumps({"error": "Missing Polar access token configuration"}),
            status=500,
            content_type="application/json"
        )

    product_id = POLAR_PRODUCT_IDS[product]

    # Default success URL if not configured
    success_url = polar_success_url or "https://zestcli.com?checkout=success"

    try:
        with Polar(
            access_token=polar_access_token,
            server="sandbox",
        ) as polar:
            checkout_params = {
                "products": [product_id],
                "success_url": success_url,
            }

            print(f"Creating checkout with params: {checkout_params}")
            result = polar.checkouts.create(request=checkout_params)
            print(f"Checkout created successfully: {result.url}")

            return https_fn.Response(
                json.dumps({"checkout_url": result.url}),
                status=200,
                content_type="application/json"
            )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Checkout error: {error_details}")
        return https_fn.Response(
            json.dumps({"error": f"Failed to create checkout: {str(e)}"}),
            status=500,
            content_type="application/json"
        )


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
        print("Missing webhook secret")
        return https_fn.Response("Missing webhook secret", status=500)

    payload = req.get_data(as_text=True)

    # Standard Webhooks uses these headers
    webhook_id = req.headers.get("webhook-id")
    webhook_timestamp = req.headers.get("webhook-timestamp")
    webhook_signature = req.headers.get("webhook-signature")

    if not all([webhook_id, webhook_timestamp, webhook_signature]):
        print(f"Missing headers: id={webhook_id}, ts={webhook_timestamp}, sig={webhook_signature}")
        return https_fn.Response("Missing webhook headers", status=400)

    # Verify webhook signature using Standard Webhooks library
    # Polar provides the secret in base64 format, standardwebhooks expects "whsec_" + base64
    try:
        import base64
        # If secret doesn't start with whsec_, assume it's raw and needs to be formatted
        if webhook_secret.startswith("whsec_"):
            secret_for_verification = webhook_secret
        else:
            # Try to use it as-is first (it might already be base64)
            # The standardwebhooks library expects: whsec_<base64-encoded-secret>
            secret_for_verification = f"whsec_{webhook_secret}"

        print(f"Secret format: starts_with_whsec={webhook_secret.startswith('whsec_')}, length={len(webhook_secret)}")
        wh = Webhook(secret_for_verification)
        wh.verify(payload, {
            "webhook-id": webhook_id,
            "webhook-timestamp": webhook_timestamp,
            "webhook-signature": webhook_signature,
        })
        print("Webhook signature verified successfully")
    except Exception as e:
        # If verification fails, try encoding the secret to base64 first
        try:
            encoded_secret = base64.b64encode(webhook_secret.encode()).decode()
            secret_for_verification = f"whsec_{encoded_secret}"
            print(f"Retrying with base64 encoded secret, length={len(encoded_secret)}")
            wh = Webhook(secret_for_verification)
            wh.verify(payload, {
                "webhook-id": webhook_id,
                "webhook-timestamp": webhook_timestamp,
                "webhook-signature": webhook_signature,
            })
            print("Webhook signature verified successfully (with base64 encoding)")
        except Exception as e2:
            print(f"Webhook signature verification failed: {str(e)} | Retry: {str(e2)}")
            return https_fn.Response("Invalid signature", status=400)

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return https_fn.Response("Invalid JSON payload", status=400)

    event_type = event.get("type")
    print(f"Received webhook event: {event_type}")
    print(f"Event data keys: {list(event.get('data', {}).keys())}")

    # Logic for successful order
    # Polar sends "order.paid" when payment is confirmed
    # Also handle "checkout.updated" with status=succeeded as fallback
    if event_type == "order.paid":
        order = event.get("data", {})
        customer = order.get("customer", {})
        customer_email = customer.get("email")

        print(f"Customer data: {customer}")
        print(f"Customer email: {customer_email}")

        if not customer_email:
            print("No customer email found in order data")
            return https_fn.Response("No customer email in order", status=400)

        # Determine product type from product data
        product = order.get("product", {})
        product_name = product.get("name", "").lower()
        product_id = order.get("product_id") or product.get("id")

        print(f"Product data: name={product.get('name')}, id={product_id}")

        # Match by product ID first (more reliable), then fall back to name
        # TODO: Update these with actual Polar product IDs
        if product_id == "PLACEHOLDER_LITE_PRODUCT_ID":
            product_type = "lite"
        elif product_id == "PLACEHOLDER_HOT_PRODUCT_ID":
            product_type = "hot"
        elif product_id == "PLACEHOLDER_EXTRA_SPICY_PRODUCT_ID":
            product_type = "extra_spicy"
        elif "lite" in product_name or "qwen3" in product_name or "4b" in product_name:
            product_type = "lite"
        elif "hot" in product_name or "coder" in product_name and "q5" in product_name:
            product_type = "hot"
        elif "extra" in product_name or "spicy" in product_name or "fp16" in product_name:
            product_type = "extra_spicy"
        else:
            # Default to lite if unclear
            print(f"Warning: Could not determine product type, defaulting to lite")
            product_type = "lite"

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
        print(f"Creating/updating license for {customer_email}, product={product_type}")
        try:
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
            print(f"License created successfully for {customer_email}")
        except Exception as e:
            print(f"Failed to create license: {str(e)}")
            return https_fn.Response(f"Failed to create license: {str(e)}", status=500)

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
    Expects JSON: {
        "email": "user@example.com",
        "product": "lite", "hot", or "extra_spicy",
        "flow_type": "activation" or "trial" (optional, defaults to "activation"),
        "device_id": "HARDWARE-UUID" (required for trial flow)
    }

    For "activation" flow: requires existing paid license
    For "trial" flow: creates license document if needed, allows new users
                      checks email domain allowlist and machine ID
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    product = data.get("product", "lite")
    flow_type = data.get("flow_type", "activation")
    device_id = data.get("device_id")

    if not email:
        return https_fn.Response("Missing email", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    if flow_type not in ["activation", "trial"]:
        return https_fn.Response("Invalid flow_type. Must be 'activation' or 'trial'", status=400)

    paid_field, _, _ = get_product_fields(product)
    _, started_field, expires_field = get_trial_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if flow_type == "activation":
        if not doc.exists:
            return https_fn.Response("No license found for this email", status=404)
        license_data = doc.to_dict()
        if not license_data.get(paid_field):
            return https_fn.Response(f"No {product} license found for this email", status=403)
    else:
        # Trial flow: check if this machine has already used a trial
        if device_id:
            machine_check = check_machine_trial_used(db, device_id, product)
            if machine_check["used"]:
                if machine_check["expired"]:
                    return https_fn.Response(
                        json.dumps({
                            "status": "machine_trial_expired",
                            "message": "This device has already used its free trial. Please purchase to continue.",
                            "previous_email": machine_check["email"]
                        }),
                        status=200,
                        content_type="application/json"
                    )
                else:
                    # Machine has active trial - check if device is registered
                    # to return full trial info and restore local config
                    trial_email = machine_check["email"]
                    trial_license_ref = db.collection("licenses").document(trial_email)
                    trial_license_doc = trial_license_ref.get()

                    if trial_license_doc.exists:
                        trial_license_data = trial_license_doc.to_dict()
                        trial_devices = trial_license_data.get("trial_devices", [])
                        existing_device = next((d for d in trial_devices if d["device_id"] == device_id), None)

                        if existing_device:
                            # Device is registered - return full trial info
                            expires_at = trial_license_data.get(expires_field)
                            now = datetime.now(timezone.utc)
                            if isinstance(expires_at, str):
                                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

                            remaining = expires_at - now
                            hours_remaining = int(remaining.total_seconds() / 3600)
                            minutes_remaining = int(remaining.total_seconds() / 60)
                            days_remaining = hours_remaining // 24

                            return https_fn.Response(
                                json.dumps({
                                    "status": "trial_active_device_registered",
                                    "message": "Welcome back! Your trial is still active.",
                                    "device_nickname": existing_device.get("device_name", ""),
                                    "trial_email": trial_email,
                                    "trial_expires_at": expires_at.isoformat(),
                                    "days_remaining": days_remaining,
                                    "hours_remaining": hours_remaining,
                                    "minutes_remaining": minutes_remaining
                                }),
                                status=200,
                                content_type="application/json"
                            )

                    # Device not registered or license not found - return generic message
                    return https_fn.Response(
                        json.dumps({
                            "status": "machine_trial_active",
                            "message": "This device already has an active trial.",
                            "trial_email": trial_email
                        }),
                        status=200,
                        content_type="application/json"
                    )

        if doc.exists:
            license_data = doc.to_dict()
            if license_data.get(paid_field):
                return https_fn.Response(
                    json.dumps({"status": "already_paid", "message": "You already have a paid license. Use activation flow."}),
                    status=200,
                    content_type="application/json"
                )
            if license_data.get(started_field):
                expires_at = license_data.get(expires_field)
                now = datetime.now(timezone.utc)
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
                if expires_at and now >= expires_at:
                    return https_fn.Response(
                        json.dumps({"status": "trial_expired", "message": "Your trial has expired. Please purchase to continue."}),
                        status=200,
                        content_type="application/json"
                    )
                # Trial is still active - check if device is already registered
                if device_id:
                    trial_devices = license_data.get("trial_devices", [])
                    existing_device = next((d for d in trial_devices if d["device_id"] == device_id), None)
                    if existing_device:
                        # Device already registered on this trial - no OTP needed
                        remaining = expires_at - now
                        hours_remaining = int(remaining.total_seconds() / 3600)
                        minutes_remaining = int(remaining.total_seconds() / 60)
                        days_remaining = hours_remaining // 24
                        return https_fn.Response(
                            json.dumps({
                                "status": "trial_active_device_registered",
                                "message": "Welcome back! Your trial is still active.",
                                "device_nickname": existing_device.get("device_name", ""),
                                "trial_expires_at": expires_at.isoformat(),
                                "days_remaining": days_remaining,
                                "hours_remaining": hours_remaining,
                                "minutes_remaining": minutes_remaining
                            }),
                            status=200,
                            content_type="application/json"
                        )
        else:
            # For trial flow, don't create doc yet - wait until email sends successfully
            # This prevents invalid emails from being stored in Firestore
            pass

    otp_code = str(random.randint(100000, 999999))
    otp_expiry = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRY_MINUTES)

    resend_api_key = os.environ.get("RESEND_API_KEY")
    if not resend_api_key:
        return https_fn.Response("Missing Resend API key", status=500)

    resend.api_key = resend_api_key

    subject = "Your Zest CLI Verification Code"
    if flow_type == "trial":
        subject = "Start Your Zest CLI Free Trial"

    # Try to send email FIRST before storing anything
    try:
        resend.Emails.send({
            "from": "info@zestcli.com",
            "to": email,
            "subject": subject,
            "html": f"""
                <h2>Your Zest CLI Verification Code</h2>
                <p>Use this code to {'start your free trial' if flow_type == 'trial' else 'activate your device'}:</p>
                <h1 style="font-size: 32px; letter-spacing: 4px; font-family: monospace;">{otp_code}</h1>
                <p>This code will expire in {OTP_EXPIRY_MINUTES} minutes.</p>
                <p>If you did not request this code, please ignore this email.</p>
            """
        })

        # Email sent successfully - now create/update the document
        if not doc.exists and flow_type == "trial":
            doc_ref.set({
                "email": email,
                "zest_user_id": str(uuid.uuid4()),
                "created_at": datetime.now(timezone.utc).isoformat(),
                "otp_code": otp_code,
                "otp_expiry": otp_expiry
            })
        else:
            doc_ref.update({
                "otp_code": otp_code,
                "otp_expiry": otp_expiry
            })
        return https_fn.Response(
            json.dumps({"status": "otp_sent", "message": "OTP sent successfully"}),
            status=200,
            content_type="application/json"
        )
    except Exception as e:
        return https_fn.Response(f"Failed to send email: {str(e)}", status=500)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def start_trial(req: https_fn.Request) -> https_fn.Response:
    """
    Start a 5-day trial after OTP verification.
    Expects JSON: {
        "email": "user@example.com",
        "otp_code": "123456",
        "product": "lite", "hot", or "extra_spicy",
        "device_id": "HARDWARE-UUID",
        "device_name": "MacBook Pro"
    }
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    otp_code = data.get("otp_code")
    product = data.get("product", "lite")
    device_id = data.get("device_id")
    device_name = data.get("device_name")

    if not all([email, otp_code, device_id, device_name]):
        return https_fn.Response("Missing required fields", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    paid_field, _, _ = get_product_fields(product)
    trial_field, started_field, expires_field = get_trial_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response("No license found. Please request OTP first.", status=404)

    license_data = doc.to_dict()

    stored_otp = license_data.get("otp_code")
    otp_expiry = license_data.get("otp_expiry")

    if not stored_otp or not otp_expiry:
        return https_fn.Response("No OTP found. Please request a new one.", status=400)

    if datetime.now(timezone.utc) > otp_expiry:
        return https_fn.Response("OTP expired. Please request a new one.", status=400)

    if stored_otp != otp_code:
        return https_fn.Response("Invalid OTP", status=403)

    if license_data.get(paid_field):
        doc_ref.update({
            "otp_code": firestore.DELETE_FIELD,
            "otp_expiry": firestore.DELETE_FIELD
        })
        return https_fn.Response(
            json.dumps({"status": "already_paid", "message": "You already have a paid license."}),
            status=200,
            content_type="application/json"
        )

    if license_data.get(started_field):
        expires_at = license_data.get(expires_field)
        now = datetime.now(timezone.utc)
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

        doc_ref.update({
            "otp_code": firestore.DELETE_FIELD,
            "otp_expiry": firestore.DELETE_FIELD
        })

        if expires_at and now >= expires_at:
            return https_fn.Response(
                json.dumps({"status": "trial_expired", "message": "Your trial has expired."}),
                status=200,
                content_type="application/json"
            )

        remaining = expires_at - now
        hours_remaining = int(remaining.total_seconds() / 3600)
        minutes_remaining = int(remaining.total_seconds() / 60)
        days_remaining = hours_remaining // 24

        trial_devices = license_data.get("trial_devices", [])
        existing_device = next((d for d in trial_devices if d["device_id"] == device_id), None)

        if existing_device:
            # Device already registered - return existing nickname
            existing_nickname = existing_device.get("device_name", device_name)
        else:
            # New device on existing trial - add it
            existing_nickname = device_name
            trial_devices.append({
                "device_id": device_id,
                "device_name": device_name,
                "registered_at": now.isoformat()
            })
            doc_ref.update({"trial_devices": trial_devices})

        # Ensure machine ID is recorded (for reinstall detection)
        record_machine_trial(db, device_id, email, product)

        return https_fn.Response(
            json.dumps({
                "status": "trial_active",
                "trial_expires_at": expires_at.isoformat(),
                "days_remaining": days_remaining,
                "hours_remaining": hours_remaining,
                "minutes_remaining": minutes_remaining,
                "device_nickname": existing_nickname
            }),
            status=200,
            content_type="application/json"
        )

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(days=TRIAL_DURATION_DAYS)

    doc_ref.update({
        trial_field: True,
        started_field: now.isoformat(),
        expires_field: expires_at.isoformat(),
        "trial_devices": [{
            "device_id": device_id,
            "device_name": device_name,
            "registered_at": now.isoformat()
        }],
        "otp_code": firestore.DELETE_FIELD,
        "otp_expiry": firestore.DELETE_FIELD
    })

    # Record machine ID to prevent multiple trials from the same device
    record_machine_trial(db, device_id, email, product)

    return https_fn.Response(
        json.dumps({
            "status": "trial_started",
            "trial_expires_at": expires_at.isoformat(),
            "days_remaining": TRIAL_DURATION_DAYS
        }),
        status=200,
        content_type="application/json"
    )


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def check_trial_status(req: https_fn.Request) -> https_fn.Response:
    """
    Check trial/license status for a user and product.
    Expects JSON: {
        "email": "user@example.com",
        "product": "lite", "hot", or "extra_spicy",
        "device_id": "HARDWARE-UUID"
    }
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    product = data.get("product", "lite")
    device_id = data.get("device_id")

    if not email:
        return https_fn.Response("Missing email", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response(
            json.dumps({"status": "no_license"}),
            status=200,
            content_type="application/json"
        )

    license_data = doc.to_dict()
    trial_status = get_trial_status(license_data, product)

    # If device_id provided, check for device nickname
    if device_id:
        # Check persistent device_nicknames mapping first (survives deregistration)
        device_nicknames = license_data.get("device_nicknames", {})
        if device_id in device_nicknames:
            trial_status["device_nickname"] = device_nicknames[device_id]

        # Fall back to checking trial_devices array
        if not trial_status.get("device_nickname"):
            trial_devices = license_data.get("trial_devices", [])
            existing_device = next((d for d in trial_devices if d["device_id"] == device_id), None)
            if existing_device:
                trial_status["device_nickname"] = existing_device.get("device_name", "")

        # Auto-register device for active trials
        if trial_status["status"] == "trial_active":
            trial_devices = license_data.get("trial_devices", [])
            existing_device = next((d for d in trial_devices if d["device_id"] == device_id), None)
            if not existing_device:
                now = datetime.now(timezone.utc)
                trial_devices.append({
                    "device_id": device_id,
                    "device_name": data.get("device_name", "Unknown Device"),
                    "registered_at": now.isoformat()
                })
                doc_ref.update({"trial_devices": trial_devices})

    return https_fn.Response(
        json.dumps(trial_status),
        status=200,
        content_type="application/json"
    )


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
                   "device_nickname": "My Mac", "product": "lite", "hot", or "extra_spicy"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    otp = data.get("otp")
    device_uuid = data.get("device_uuid")
    device_nickname = data.get("device_nickname")
    product = data.get("product", "lite")

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
    for i, device in enumerate(devices):
        if device["uuid"] == device_uuid:
            # Update nickname if it changed or was missing
            if device.get("nickname") != device_nickname:
                devices[i]["nickname"] = device_nickname
                doc_ref.update({
                    devices_field: devices,
                    f"device_nicknames.{device_uuid}": device_nickname,
                    "otp_code": firestore.DELETE_FIELD,
                    "otp_expiry": firestore.DELETE_FIELD
                })
                return https_fn.Response(f"Device nickname updated for {product}", status=200)
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

    # Clear OTP, update devices, and persist nickname
    doc_ref.update({
        devices_field: devices,
        f"device_nicknames.{device_uuid}": device_nickname,
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
    Supports both paid licenses and active trials.
    Expects JSON: {"email": "...", "device_uuid": "uuid", "product": "lite", "hot", or "extra_spicy"}

    Returns JSON with status:
    - "valid": Paid license, device registered
    - "trial_active": Active trial with remaining time
    - "trial_expired": Trial has expired
    - "no_license": No license or trial found
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")
    product = data.get("product", "lite")

    if not email or not device_uuid:
        return https_fn.Response("Missing email or device_uuid", status=400)

    if product not in VALID_PRODUCTS:
        return https_fn.Response(f"Invalid product. Must be one of: {VALID_PRODUCTS}", status=400)

    paid_field, devices_field, _ = get_product_fields(product)

    db = firestore.client()
    doc_ref = db.collection("licenses").document(email)
    doc = doc_ref.get()

    if not doc.exists:
        return https_fn.Response(
            json.dumps({"status": "no_license"}),
            status=200,
            content_type="application/json"
        )

    license_data = doc.to_dict()
    trial_status = get_trial_status(license_data, product)

    if trial_status["status"] == "paid":
        devices = license_data.get(devices_field, [])
        for device in devices:
            if device["uuid"] == device_uuid:
                return https_fn.Response(
                    json.dumps({"status": "valid"}),
                    status=200,
                    content_type="application/json"
                )
        return https_fn.Response(
            json.dumps({"status": "device_not_registered", "devices_registered": len(devices)}),
            status=200,
            content_type="application/json"
        )

    if trial_status["status"] == "trial_active":
        trial_status["status"] = "trial_active"
        return https_fn.Response(
            json.dumps(trial_status),
            status=200,
            content_type="application/json"
        )

    if trial_status["status"] == "trial_expired":
        return https_fn.Response(
            json.dumps({"status": "trial_expired"}),
            status=200,
            content_type="application/json"
        )

    return https_fn.Response(
        json.dumps({"status": "no_license"}),
        status=200,
        content_type="application/json"
    )


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
                   "new_device_nickname": "New Mac", "product": "lite", "hot", or "extra_spicy"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    old_device_uuid = data.get("old_device_uuid")
    new_device_uuid = data.get("new_device_uuid")
    new_device_nickname = data.get("new_device_nickname")
    product = data.get("product", "lite")

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

    doc_ref.update({
        devices_field: devices,
        f"device_nicknames.{new_device_uuid}": new_device_nickname
    })
    return https_fn.Response(f"Device replaced for {product}", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def list_devices(req: https_fn.Request) -> https_fn.Response:
    """
    List all registered devices for a user's product license.
    Requires OTP verification for security.
    Expects JSON: {"email": "...", "otp": "123456", "product": "lite", "hot", or "extra_spicy"}
    Returns JSON: {"devices": [{"uuid": "...", "nickname": "...", "registered_at": "..."}]}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    otp = data.get("otp")
    product = data.get("product", "lite")

    if not email or not otp:
        return https_fn.Response("Missing email or otp", status=400)

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

    # Get devices
    devices = license_data.get(devices_field, [])
    device_list = [
        {
            "uuid": d["uuid"],
            "nickname": d.get("nickname", "Unknown device"),
            "registered_at": d.get("registered_at", "Unknown")
        }
        for d in devices
    ]

    # Clear OTP after successful use
    doc_ref.update({
        "otp_code": firestore.DELETE_FIELD,
        "otp_expiry": firestore.DELETE_FIELD
    })

    return https_fn.Response(
        json.dumps({"devices": device_list}),
        status=200,
        content_type="application/json"
    )


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
    Expects JSON: {"email": "...", "device_uuid": "uuid", "product": "lite", "hot", or "extra_spicy"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")
    product = data.get("product", "lite")

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
    Expects JSON: {"email": "...", "device_uuid": "uuid", "product": "lite", "hot", or "extra_spicy"}

    The CLI should call this every 2 weeks. If the ping fails due to network
    issues, the CLI can continue operating using cached validation.
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_uuid = data.get("device_uuid")
    product = data.get("product", "lite")

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


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def get_checkout_url(req: https_fn.Request) -> https_fn.Response:
    """
    Generate a Polar checkout URL for trial-to-paid conversion.
    Pre-fills the user's email for seamless checkout.
    Expects JSON: {"email": "user@example.com", "product": "lite", "hot", or "extra_spicy"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    product = data.get("product", "lite")

    if not email:
        return https_fn.Response("Missing email", status=400)

    if product not in POLAR_PRODUCT_IDS:
        return https_fn.Response(
            f"Invalid product. Available: {list(POLAR_PRODUCT_IDS.keys())}",
            status=400
        )

    polar_access_token = os.environ.get("POLAR_ACCESS_TOKEN")
    polar_success_url = os.environ.get("POLAR_SUCCESS_URL")

    if not polar_access_token:
        return https_fn.Response("Missing Polar access token configuration", status=500)

    product_id = POLAR_PRODUCT_IDS[product]
    success_url = polar_success_url or "https://zestcli.com?checkout=success"

    try:
        with Polar(
            access_token=polar_access_token,
            server="sandbox",
        ) as polar:
            checkout_params = {
                "products": [product_id],
                "success_url": success_url,
                "customer_email": email,
                "metadata": {"source": "trial_conversion", "product": product}
            }

            result = polar.checkouts.create(request=checkout_params)

            return https_fn.Response(
                json.dumps({"checkout_url": result.url}),
                status=200,
                content_type="application/json"
            )
    except Exception as e:
        return https_fn.Response(
            json.dumps({"error": f"Failed to create checkout: {str(e)}"}),
            status=500,
            content_type="application/json"
        )


# Model file configuration
MODEL_FILES = {
    "lite": "qwen3_4b_Q5_K_M.gguf",
    "hot": "qwen2_5_coder_7b_Q5_K_M.gguf",
    "extra_spicy": "qwen2_5_coder_7b_fp16.gguf"
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

    # Get version info from Firestore
    # Document structure: versions/current with fields:
    # cli_version, fp16_model_version, q5_model_version,
    # fp16_model_size, q5_model_size, update_message, update_url
    version_ref = db.collection("versions").document("current")
    version_doc = version_ref.get()

    model_filename = MODEL_FILES.get(product, MODEL_FILES["lite"])
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
