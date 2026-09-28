"""
Shared helper functions for Zest CLI cloud functions.
"""

from datetime import datetime, timezone, timedelta

from config import MAX_OTP_SENDS_PER_HOUR, MAX_OTP_VERIFY_ATTEMPTS


def check_otp_send_rate(db, email: str) -> bool:
    """
    Check if the email has exceeded the OTP send rate limit.
    Returns True if the request is allowed, False if rate limited.
    """
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)

    rate_ref = db.collection("rate_limits").document(email)
    rate_doc = rate_ref.get()

    if not rate_doc.exists:
        rate_ref.set({"otp_sends": [now.isoformat()]})
        return True

    rate_data = rate_doc.to_dict()
    sends = rate_data.get("otp_sends", [])

    recent_sends = [
        ts for ts in sends
        if datetime.fromisoformat(ts) > one_hour_ago
    ]

    if len(recent_sends) >= MAX_OTP_SENDS_PER_HOUR:
        return False

    recent_sends.append(now.isoformat())
    rate_ref.update({"otp_sends": recent_sends})
    return True


def check_otp_verify_attempt(db, email: str) -> bool:
    """
    Track failed OTP verification attempts.
    Returns True if the attempt is allowed, False if locked out.
    Resets on successful verification (caller must call reset_otp_verify_attempts).
    """
    rate_ref = db.collection("rate_limits").document(email)
    rate_doc = rate_ref.get()

    if not rate_doc.exists:
        rate_ref.set({"otp_failed_attempts": 1})
        return True

    rate_data = rate_doc.to_dict()
    attempts = rate_data.get("otp_failed_attempts", 0)

    if attempts >= MAX_OTP_VERIFY_ATTEMPTS:
        return False

    rate_ref.update({"otp_failed_attempts": attempts + 1})
    return True


def reset_otp_verify_attempts(db, email: str):
    """Reset the failed OTP attempt counter after successful verification."""
    rate_ref = db.collection("rate_limits").document(email)
    rate_ref.set({"otp_failed_attempts": 0}, merge=True)


# Field names on licenses/{email} documents. There is a single product now,
# so these are flat constants rather than per-product functions.
PAID_FIELD = "is_paid"
DEVICES_FIELD = "devices"
ORDER_FIELD = "polar_order_id"
TRIAL_FIELD = "is_trial"
TRIAL_STARTED_FIELD = "trial_started_at"
TRIAL_EXPIRES_FIELD = "trial_expires_at"
TRIAL_DEVICES_FIELD = "trial_devices"


def check_machine_trial_used(db, device_id: str) -> dict:
    """
    Check if a machine ID has already been used for a trial on any email.
    Returns {"used": bool, "email": str or None, "expired": bool or None}.
    """
    if not device_id:
        return {"used": False, "email": None, "expired": None}

    machine_ref = db.collection("trial_machines").document(device_id)
    machine_doc = machine_ref.get()

    if not machine_doc.exists:
        return {"used": False, "email": None, "expired": None}

    machine_data = machine_doc.to_dict()
    trial_email = machine_data.get("trial_email")

    if not trial_email:
        return {"used": False, "email": None, "expired": None}

    license_ref = db.collection("licenses").document(trial_email)
    license_doc = license_ref.get()

    if not license_doc.exists:
        return {"used": True, "email": trial_email, "expired": True}

    license_data = license_doc.to_dict()
    expires_at = license_data.get(TRIAL_EXPIRES_FIELD)

    if expires_at:
        now = datetime.now(timezone.utc)
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
        expired = now >= expires_at
        return {"used": True, "email": trial_email, "expired": expired}

    return {"used": True, "email": trial_email, "expired": True}


def record_machine_trial(db, device_id: str, email: str):
    """Record that a machine ID has been used for a trial."""
    if not device_id:
        return

    machine_ref = db.collection("trial_machines").document(device_id)
    machine_ref.set({
        "trial_email": email,
        "trial_started_at": datetime.now(timezone.utc).isoformat(),
        "last_updated": datetime.now(timezone.utc).isoformat()
    }, merge=True)


def get_trial_status(license_data: dict) -> dict:
    """
    Check trial/license status for a user. Returns a dict with:
    - status: "paid", "trial_active", "trial_expired", or "no_license"
    - Additional fields depending on status
    """
    if license_data.get(PAID_FIELD):
        devices = license_data.get(DEVICES_FIELD, [])
        return {"status": "paid", "devices_registered": len(devices)}

    if license_data.get(TRIAL_FIELD):
        expires_at = license_data.get(TRIAL_EXPIRES_FIELD)
        if expires_at:
            now = datetime.now(timezone.utc)
            if isinstance(expires_at, str):
                expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            if now < expires_at:
                remaining = expires_at - now
                hours_remaining = int(remaining.total_seconds() / 3600)
                days_remaining = (hours_remaining + 23) // 24  # Ceiling division
                return {
                    "status": "trial_active",
                    "days_remaining": days_remaining,
                    "hours_remaining": hours_remaining,
                    "trial_expires_at": expires_at.isoformat()
                }
            else:
                return {"status": "trial_expired"}

    return {"status": "no_license"}
