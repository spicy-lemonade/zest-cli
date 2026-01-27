"""
Device management cloud functions for Zest CLI.
"""

import json
from datetime import datetime, timezone
from firebase_functions import https_fn, options
from firebase_admin import firestore

from config import VALID_PRODUCTS, SERVICE_ACCOUNT_EMAIL
from helpers import get_product_fields, get_trial_status


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
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
    trial_status_result = get_trial_status(license_data, product)

    if trial_status_result["status"] == "paid":
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

    if trial_status_result["status"] == "trial_active":
        trial_status_result["status"] = "trial_active"
        return https_fn.Response(
            json.dumps(trial_status_result),
            status=200,
            content_type="application/json"
        )

    if trial_status_result["status"] == "trial_expired":
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
    service_account=SERVICE_ACCOUNT_EMAIL,
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
    service_account=SERVICE_ACCOUNT_EMAIL,
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

    stored_otp = license_data.get("otp_code")
    otp_expiry = license_data.get("otp_expiry")

    if not stored_otp or not otp_expiry:
        return https_fn.Response("No OTP found. Please request a new one.", status=400)

    if datetime.now(timezone.utc) > otp_expiry:
        return https_fn.Response("OTP expired. Please request a new one.", status=400)

    if stored_otp != otp:
        return https_fn.Response("Invalid OTP", status=403)

    if not license_data.get(paid_field):
        return https_fn.Response(f"No {product} license found", status=403)

    devices = license_data.get(devices_field, [])
    device_list = [
        {
            "uuid": d["uuid"],
            "nickname": d.get("nickname", "Unknown device"),
            "registered_at": d.get("registered_at", "Unknown")
        }
        for d in devices
    ]

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
    service_account=SERVICE_ACCOUNT_EMAIL,
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

    devices = [d for d in devices if d["uuid"] != device_uuid]

    doc_ref.update({devices_field: devices})
    return https_fn.Response(f"Device deregistered from {product}", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
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
