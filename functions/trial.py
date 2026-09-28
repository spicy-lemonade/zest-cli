"""
Trial management cloud functions for Zest CLI.
"""

import hmac
import json
from datetime import datetime, timezone, timedelta
from firebase_functions import https_fn, options
from firebase_admin import firestore

from config import TRIAL_DURATION_DAYS, SERVICE_ACCOUNT_EMAIL
from helpers import (
    PAID_FIELD,
    TRIAL_FIELD,
    TRIAL_STARTED_FIELD,
    TRIAL_EXPIRES_FIELD,
    TRIAL_DEVICES_FIELD,
    record_machine_trial,
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
def check_device_trial(req: https_fn.Request) -> https_fn.Response:
    """
    Check if a device already has an active trial (without requiring email).
    Expects JSON: {"device_id": "HARDWARE-UUID"}
    Returns:
    - {"status": "no_trial"} if device has no trial
    - {"status": "trial_active", "email": "...", ...} if device has active trial
    - {"status": "trial_expired", "email": "..."} if device trial expired
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    device_id = data.get("device_id")

    if not device_id:
        return https_fn.Response("Missing device_id", status=400)

    db = firestore.client()

    machine_ref = db.collection("trial_machines").document(device_id)
    machine_doc = machine_ref.get()

    if not machine_doc.exists:
        return https_fn.Response(
            json.dumps({"status": "no_trial"}),
            status=200,
            content_type="application/json"
        )

    machine_data = machine_doc.to_dict()
    trial_email = machine_data.get("trial_email")

    if not trial_email:
        return https_fn.Response(
            json.dumps({"status": "no_trial"}),
            status=200,
            content_type="application/json"
        )

    license_ref = db.collection("licenses").document(trial_email)
    license_doc = license_ref.get()

    if not license_doc.exists:
        return https_fn.Response(
            json.dumps({
                "status": "trial_expired",
                "email": trial_email,
                "message": "This device has already used its free trial."
            }),
            status=200,
            content_type="application/json"
        )

    license_data = license_doc.to_dict()
    expires_at = license_data.get(TRIAL_EXPIRES_FIELD)

    if not expires_at:
        return https_fn.Response(
            json.dumps({
                "status": "trial_expired",
                "email": trial_email,
                "message": "This device has already used its free trial."
            }),
            status=200,
            content_type="application/json"
        )

    now = datetime.now(timezone.utc)
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))

    if now >= expires_at:
        return https_fn.Response(
            json.dumps({
                "status": "trial_expired",
                "email": trial_email,
                "message": "This device has already used its free trial."
            }),
            status=200,
            content_type="application/json"
        )

    remaining = expires_at - now
    hours_remaining = int(remaining.total_seconds() / 3600)
    minutes_remaining = int(remaining.total_seconds() / 60)
    days_remaining = (hours_remaining + 23) // 24

    trial_devices = license_data.get(TRIAL_DEVICES_FIELD, [])
    existing_device = next((d for d in trial_devices if d.get("device_id") == device_id), None)
    device_nickname = existing_device.get("device_name", "") if existing_device else ""

    return https_fn.Response(
        json.dumps({
            "status": "trial_active",
            "email": trial_email,
            "device_nickname": device_nickname,
            "trial_expires_at": expires_at.isoformat(),
            "days_remaining": days_remaining,
            "hours_remaining": hours_remaining,
            "minutes_remaining": minutes_remaining
        }),
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
def start_trial(req: https_fn.Request) -> https_fn.Response:
    """
    Start a 5-day trial after OTP verification.
    Expects JSON: {
        "email": "user@example.com",
        "otp_code": "123456",
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
    device_id = data.get("device_id")
    device_name = data.get("device_name")

    if not all([email, otp_code, device_id, device_name]):
        return https_fn.Response("Missing required fields", status=400)

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

    if not hmac.compare_digest(stored_otp, otp_code):
        if not check_otp_verify_attempt(db, email):
            doc_ref.update({
                "otp_code": firestore.DELETE_FIELD,
                "otp_expiry": firestore.DELETE_FIELD
            })
            return https_fn.Response("Too many failed attempts. OTP invalidated. Please request a new one.", status=429)
        return https_fn.Response("Invalid OTP", status=403)

    reset_otp_verify_attempts(db, email)

    if license_data.get(PAID_FIELD):
        doc_ref.update({
            "otp_code": firestore.DELETE_FIELD,
            "otp_expiry": firestore.DELETE_FIELD
        })
        return https_fn.Response(
            json.dumps({"status": "already_paid", "message": "You already have a paid license."}),
            status=200,
            content_type="application/json"
        )

    if license_data.get(TRIAL_STARTED_FIELD):
        expires_at = license_data.get(TRIAL_EXPIRES_FIELD)
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
        days_remaining = (hours_remaining + 23) // 24  # Ceiling division

        trial_devices = license_data.get(TRIAL_DEVICES_FIELD, [])
        existing_device = next((d for d in trial_devices if d.get("device_id") == device_id), None)

        if existing_device:
            existing_nickname = existing_device.get("device_name", device_name)
        else:
            existing_nickname = device_name
            trial_devices.append({
                "device_id": device_id,
                "device_name": device_name,
                "registered_at": now.isoformat()
            })
            doc_ref.update({TRIAL_DEVICES_FIELD: trial_devices})

        record_machine_trial(db, device_id, email)

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
        TRIAL_FIELD: True,
        TRIAL_STARTED_FIELD: now.isoformat(),
        TRIAL_EXPIRES_FIELD: expires_at.isoformat(),
        TRIAL_DEVICES_FIELD: [{
            "device_id": device_id,
            "device_name": device_name,
            "registered_at": now.isoformat()
        }],
        "otp_code": firestore.DELETE_FIELD,
        "otp_expiry": firestore.DELETE_FIELD
    })

    record_machine_trial(db, device_id, email)

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
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def check_trial_status(req: https_fn.Request) -> https_fn.Response:
    """
    Check trial/license status for a user.
    Expects JSON: {
        "email": "user@example.com",
        "device_id": "HARDWARE-UUID"
    }
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    device_id = data.get("device_id")

    if not email:
        return https_fn.Response("Missing email", status=400)

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

    if device_id:
        device_nicknames = license_data.get("device_nicknames", {})
        if device_id in device_nicknames:
            trial_status_result["device_nickname"] = device_nicknames[device_id]

        if not trial_status_result.get("device_nickname"):
            trial_devices = license_data.get(TRIAL_DEVICES_FIELD, [])
            existing_device = next((d for d in trial_devices if d.get("device_id") == device_id), None)
            if existing_device:
                trial_status_result["device_nickname"] = existing_device.get("device_name", "")

        if trial_status_result["status"] == "trial_active":
            trial_devices = license_data.get(TRIAL_DEVICES_FIELD, [])
            existing_device = next((d for d in trial_devices if d.get("device_id") == device_id), None)
            if not existing_device:
                now = datetime.now(timezone.utc)
                trial_devices.append({
                    "device_id": device_id,
                    "device_name": data.get("device_name", "Unknown Device"),
                    "registered_at": now.isoformat()
                })
                doc_ref.update({TRIAL_DEVICES_FIELD: trial_devices})

    return https_fn.Response(
        json.dumps(trial_status_result),
        status=200,
        content_type="application/json"
    )
