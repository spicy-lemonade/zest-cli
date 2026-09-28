"""
Device management cloud functions for Zest CLI.
"""

import hmac
import json
from datetime import datetime, timezone
from firebase_functions import https_fn, options
from firebase_admin import firestore

from config import SERVICE_ACCOUNT_EMAIL
from helpers import (
    PAID_FIELD,
    DEVICES_FIELD,
    get_trial_status,
    check_otp_verify_attempt,
    reset_otp_verify_attempts,
)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def validate_device(req: https_fn.Request) -> https_fn.Response:
    """
    Validate that a device is registered and licensed.
    Supports both paid licenses and active trials.
    Expects JSON: {"email": "...", "device_uuid": "uuid"}

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

    if not email or not device_uuid:
        return https_fn.Response("Missing email or device_uuid", status=400)

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
    trial_status_result = get_trial_status(license_data)

    if trial_status_result["status"] == "paid":
        devices = license_data.get(DEVICES_FIELD, [])
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
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def replace_device(req: https_fn.Request) -> https_fn.Response:
    """
    Replace an old device with a new one.
    Expects JSON: {"email": "...", "old_device_uuid": "uuid", "new_device_uuid": "uuid",
                   "new_device_nickname": "New Mac"}
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
    devices = license_data.get(DEVICES_FIELD, [])

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
        DEVICES_FIELD: devices,
        f"device_nicknames.{new_device_uuid}": new_device_nickname
    })
    return https_fn.Response("Device replaced", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def list_devices(req: https_fn.Request) -> https_fn.Response:
    """
    List all registered devices for a user's license.
    Requires OTP verification for security.
    Expects JSON: {"email": "...", "otp": "123456"}
    Returns JSON: {"devices": [{"uuid": "...", "nickname": "...", "registered_at": "..."}]}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    otp = data.get("otp")

    if not email or not otp:
        return https_fn.Response("Missing email or otp", status=400)

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

    if not hmac.compare_digest(stored_otp, otp):
        if not check_otp_verify_attempt(db, email):
            doc_ref.update({
                "otp_code": firestore.DELETE_FIELD,
                "otp_expiry": firestore.DELETE_FIELD
            })
            return https_fn.Response("Too many failed attempts. OTP invalidated. Please request a new one.", status=429)
        return https_fn.Response("Invalid OTP", status=403)

    reset_otp_verify_attempts(db, email)

    if not license_data.get(PAID_FIELD):
        return https_fn.Response("No license found", status=403)

    devices = license_data.get(DEVICES_FIELD, [])
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
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def deregister_device(req: https_fn.Request) -> https_fn.Response:
    """
    Remove a device from the license.
    Expects JSON: {"email": "...", "device_uuid": "uuid"}
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
    devices = license_data.get(DEVICES_FIELD, [])

    devices = [d for d in devices if d["uuid"] != device_uuid]

    doc_ref.update({DEVICES_FIELD: devices})
    return https_fn.Response("Device deregistered", status=200)


@https_fn.on_request(
    region="europe-west1",
    cors=options.CorsOptions(
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def license_heartbeat(req: https_fn.Request) -> https_fn.Response:
    """
    Biweekly license validation ping from the CLI.
    Updates last_validated timestamp for the device.
    Expects JSON: {"email": "...", "device_uuid": "uuid"}

    The CLI should call this every 2 weeks. If the ping fails due to network
    issues, the CLI can continue operating using cached validation.
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

    if not license_data.get(PAID_FIELD):
        return https_fn.Response("No license found", status=403)

    devices = license_data.get(DEVICES_FIELD, [])
    device_found = False
    now = datetime.now(timezone.utc)

    for i, device in enumerate(devices):
        if device["uuid"] == device_uuid:
            device_found = True
            devices[i]["last_validated"] = now.isoformat()
            devices[i]["last_validated_unix"] = int(now.timestamp())
            break

    if not device_found:
        return https_fn.Response("Device not registered", status=403)

    doc_ref.update({DEVICES_FIELD: devices})
    return https_fn.Response(json.dumps({
        "status": "valid",
        "validated_at": now.isoformat(),
        "validated_at_unix": int(now.timestamp())
    }), status=200, content_type="application/json")
