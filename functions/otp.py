"""
OTP generation and verification cloud functions for Zest CLI.
"""

import os
import json
import random
import uuid
from datetime import datetime, timezone, timedelta
from firebase_functions import https_fn, options
from firebase_admin import firestore
import resend

from config import (
    MAX_DEVICES_PER_PRODUCT,
    OTP_EXPIRY_MINUTES,
    VALID_PRODUCTS,
    SERVICE_ACCOUNT_EMAIL,
)
from helpers import (
    get_product_fields,
    get_trial_fields,
    check_machine_trial_used,
)


@https_fn.on_request(
    region="europe-west1",
    secrets=["RESEND_API_KEY"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
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
                    trial_email = machine_check["email"]
                    trial_license_ref = db.collection("licenses").document(trial_email)
                    trial_license_doc = trial_license_ref.get()

                    if trial_license_doc.exists:
                        trial_license_data = trial_license_doc.to_dict()
                        trial_devices = trial_license_data.get("trial_devices", [])
                        existing_device = next((d for d in trial_devices if d["device_id"] == device_id), None)

                        if existing_device:
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
                if device_id:
                    trial_devices = license_data.get("trial_devices", [])
                    existing_device = next((d for d in trial_devices if d["device_id"] == device_id), None)
                    if existing_device:
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
    service_account=SERVICE_ACCOUNT_EMAIL,
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

    for i, device in enumerate(devices):
        if device["uuid"] == device_uuid:
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

    now = datetime.now(timezone.utc)
    devices.append({
        "uuid": device_uuid,
        "nickname": device_nickname,
        "registered_at": now.isoformat(),
        "registered_at_unix": int(now.timestamp()),
        "last_validated": now.isoformat(),
        "last_validated_unix": int(now.timestamp())
    })

    doc_ref.update({
        devices_field: devices,
        f"device_nicknames.{device_uuid}": device_nickname,
        "otp_code": firestore.DELETE_FIELD,
        "otp_expiry": firestore.DELETE_FIELD
    })

    return https_fn.Response(f"Device registered for {product}", status=200)
