"""
Trial flow management for Zest CLI.
Handles trial start, expiration prompts, and pending checkout auto-activation.
"""

import os
import sys
import subprocess
import time
import requests
from datetime import datetime, timezone

from config import (
    API_BASE, PRODUCT_NAME, MODEL_PATH, TRIAL_CHECK_INTERVAL,
    load_config, save_config, format_connection_error
)


def _delete_model_file():
    """Delete the model file from disk when trial expires."""
    if os.path.exists(MODEL_PATH):
        try:
            os.remove(MODEL_PATH)
        except OSError:
            pass


def get_hw_id():
    """Get the macOS Hardware UUID."""
    cmd = 'ioreg -d2 -c IOPlatformExpertDevice | awk -F"\\"" \'/IOPlatformUUID/{print $(NF-1)}\''
    return subprocess.check_output(cmd, shell=True).decode().strip()


def check_trial_status_with_server(email: str, device_id: str) -> dict | None:
    """Check trial status with the server. Returns status dict or None on error."""
    try:
        res = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": email, "device_id": device_id},
            timeout=15
        )
        if res.status_code == 200:
            return res.json()
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None


def check_pending_checkout_and_activate() -> bool | str | None:
    """
    Check if user has a pending checkout and attempt auto-activation.
    Returns True if activation succeeded, False if should proceed to paid activation,
    "start_trial" if user wants to start a trial, "purchase" if user wants to retry purchase,
    None if no pending checkout.
    """
    # Local import to avoid circular dependency
    from activation import activate_paid_license

    config = load_config()
    pending = config.get("pending_checkout")

    if not pending:
        return None

    pending_email = pending.get("email")
    pending_time = pending.get("timestamp", 0)

    # Only consider checkouts from the last 24 hours
    if (time.time() - pending_time) > 86400:
        del config["pending_checkout"]
        save_config(config)
        return None

    hw_id = get_hw_id()

    print(f"\n\033[2K\r🌶️ Checking payment status...", end="", flush=True)
    try:
        res = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": pending_email, "device_id": hw_id},
            timeout=15
        )
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "paid":
                print("\033[2K\r✅ Payment confirmed!")
                print(f"   License email: {pending_email}")
                print("   ⚠️  If this email is wrong, press Ctrl+C and contact info@zestcli.com")
                print("")
                del config["pending_checkout"]
                save_config(config)
                return activate_paid_license(pending_email)
            else:
                print("\033[2K\r")
                print(f"🍋 Payment not yet received for {pending_email}.")
                print("   If you just completed payment, it may take a moment to process.")
                print("")
                print("   [1] Check again")
                print("   [2] Activate my license (requires email verification)")
                print("   [3] Start free trial")
                print("   [4] Purchase a license")
                print("   [5] Exit")
                print("")
                while True:
                    choice = input("Enter choice [1/2/3/4/5]: ").strip()
                    if choice == "1":
                        return check_pending_checkout_and_activate()
                    elif choice == "2":
                        del config["pending_checkout"]
                        save_config(config)
                        return False
                    elif choice == "3":
                        del config["pending_checkout"]
                        save_config(config)
                        return "start_trial"
                    elif choice == "4":
                        del config["pending_checkout"]
                        save_config(config)
                        return "purchase"
                    elif choice == "5":
                        del config["pending_checkout"]
                        save_config(config)
                        print("👋 Goodbye!")
                        sys.exit(0)
                    else:
                        print("   Please enter 1, 2, 3, 4, or 5.")
    except requests.exceptions.RequestException as e:
        print("\033[2K\r")
        print(f"⚠️  Could not check payment status: {format_connection_error(e)}")
        print("   This may be a temporary network issue.")
        print("")
        print("   [1] Retry")
        print("   [2] Activate my license (requires email verification)")
        print("   [3] Start free trial")
        print("   [4] Purchase a license")
        print("   [5] Exit")
        print("")
        while True:
            choice = input("Enter choice [1/2/3/4/5]: ").strip()
            if choice == "1":
                return check_pending_checkout_and_activate()
            elif choice == "2":
                del config["pending_checkout"]
                save_config(config)
                return False
            elif choice == "3":
                del config["pending_checkout"]
                save_config(config)
                return "start_trial"
            elif choice == "4":
                del config["pending_checkout"]
                save_config(config)
                return "purchase"
            elif choice == "5":
                del config["pending_checkout"]
                save_config(config)
                print("👋 Goodbye! Run zest again to retry.")
                sys.exit(0)
            else:
                print("   Please enter 1, 2, 3, 4, or 5.")


def show_trial_expired_prompt(email: str) -> bool:
    """
    Show options when trial expires.
    Returns True if user wants to activate paid license, False otherwise.
    """
    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  ❗ Your free trial of {PRODUCT_NAME} has expired.")
    print("│")
    print("│  Your model file has been removed.")
    print("│  Purchase a license to continue using Zest.")
    print("│")
    print("│  [1] Purchase Zest")
    print("│  [2] I already paid - activate my license")
    print("│  [3] Exit")
    print("└─────────────────────────────────────────────────┘")
    print("")

    while True:
        choice = input("Enter choice [1/2/3]: ").strip()
        if choice == "1":
            print("\n\033[2K\r🌶️ Getting checkout link...", end="", flush=True)
            try:
                res = requests.post(
                    f"{API_BASE}/get_checkout_url",
                    json={"email": email},
                    timeout=30
                )
                if res.status_code == 200:
                    data = res.json()
                    checkout_url = data.get("checkout_url")
                    if checkout_url:
                        print("\033[2K\r")
                        print(f"🍋 Opening checkout in your browser...")
                        print(f"   {checkout_url}")
                        subprocess.run(["open", checkout_url], check=False)
                        # Save pending checkout state for auto-activation on next run
                        config = load_config()
                        config["pending_checkout"] = {
                            "email": email,
                            "timestamp": time.time()
                        }
                        save_config(config)
                        print("")
                        print("   After payment, run a zest query to activate.")
                        print("   For example: zest list all files in Downloads")
                        return False
                print(f"\033[2K\r❌ Could not get checkout URL (status {res.status_code}). Visit https://zestcli.com")
            except requests.exceptions.RequestException as e:
                print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}. Visit https://zestcli.com")
            return False
        elif choice == "2":
            return True
        elif choice == "3":
            print("👋 Goodbye!")
            sys.exit(0)
        else:
            print("   Please enter 1, 2, or 3.")


def _check_device_trial(hw_id: str) -> dict | None:
    """
    Check if device already has a trial before asking for email.
    Returns trial data dict if device has active/expired trial, None otherwise.
    """
    try:
        res = requests.post(
            f"{API_BASE}/check_device_trial",
            json={"device_id": hw_id},
            timeout=15
        )
        if res.status_code == 200:
            data = res.json()
            status = data.get("status")
            if status in ["trial_active", "trial_expired"]:
                return data
            # Unexpected status - device not recognized
            return None
        # Non-200 response - log for debugging
        print(f"\033[2K\r⚠️  Device check returned status {res.status_code}")
    except requests.exceptions.Timeout:
        print("\033[2K\r⚠️  Device check timed out")
    except requests.exceptions.RequestException as e:
        print(f"\033[2K\r⚠️  Device check failed: {format_connection_error(e)}")
    return None


def _handle_existing_device_trial(device_trial: dict, hw_id: str) -> bool | None:
    """
    Handle the case where the device already has a trial.
    Returns True if trial restored, False to switch flow, None to continue to email prompt.
    """
    status = device_trial.get("status")
    trial_email = device_trial.get("email", "")
    device_nickname = device_trial.get("device_nickname", "this device")

    if status == "trial_expired":
        print(f"\n⚠️  This device has already used its free trial.")
        if trial_email:
            print(f"   Previously registered with: {trial_email}")
        if show_trial_expired_prompt(trial_email):
            return False
        sys.exit(0)

    if status == "trial_active":
        days = device_trial.get("days_remaining", 0)
        hours = device_trial.get("hours_remaining", 0)
        minutes = device_trial.get("minutes_remaining", 0)
        expires_at = device_trial.get("trial_expires_at")

        print(f"\n🍋 This device already has an active trial!")
        print(f"   Email: {trial_email}")
        if device_nickname:
            print(f"   Device: \"{device_nickname}\"")
        if days > 0:
            print(f"   Time remaining: {days} days")
        elif hours > 0:
            print(f"   Time remaining: {hours} hours")
        elif minutes > 0:
            print(f"   Time remaining: {minutes} minutes")
        print("")
        print("   [1] Continue with this trial")
        print("   [2] Cancel")
        print("")

        while True:
            choice = input("Enter choice [1/2]: ").strip()
            if choice == "1":
                config = load_config()
                config["trial"] = {
                    "email": trial_email,
                    "is_trial": True,
                    "trial_expires_at": expires_at,
                    "trial_last_checked": time.time(),
                    "device_nickname": device_nickname
                }
                save_config(config)
                print("\n🍋 Trial restored! Just a moment...")
                return True
            elif choice == "2":
                print("Goodbye!")
                sys.exit(0)
            else:
                print("   Please enter 1 or 2.")

    return None


def start_trial_flow() -> bool:
    """
    Start a free trial.
    Returns True if trial started successfully, False otherwise.
    """
    hw_id = get_hw_id()

    print(f"\n\033[2K\r🌶️ Checking device...", end="", flush=True)
    device_trial = _check_device_trial(hw_id)

    if device_trial:
        print("\033[2K\r", end="")
        result = _handle_existing_device_trial(device_trial, hw_id)
        if result is not None:
            return result

    print(f"\033[2K\r🍋 Start your free trial of {PRODUCT_NAME}")

    # Email entry loop with retry on errors
    while True:
        email = input("Enter your email: ").strip()

        if not email or "@" not in email:
            print("❌ Please enter a valid email address.")
            continue

        print(f"\033[2K\r🌶️ Sending verification code to {email}...", end="", flush=True)
        try:
            otp_res = requests.post(
                f"{API_BASE}/send_otp",
                json={"email": email, "flow_type": "trial", "device_id": hw_id},
                timeout=30
            )
            if otp_res.status_code == 200:
                data = otp_res.json()
                result = _handle_otp_response(data, email)
                if result is not None:
                    return result
                # If result is None, OTP was sent successfully, break loop
                break
            else:
                print(f"\033[2K\r❌ Error: {otp_res.text}")
                print("   Please try again or press Ctrl+C to cancel.")
                continue
        except requests.exceptions.RequestException as e:
            print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}")
            print("   Please try again or press Ctrl+C to cancel.")
            continue

    print("\033[2K\r📧 Verification code sent!")

    print("")
    print("💻 Enter a nickname for this device")
    print("   (e.g., \"John's laptop\", \"Work MacBook\")")
    while True:
        nickname = input("   Nickname: ").strip()
        if nickname:
            break
        print("   ⚠️  Nickname is required.")

    # OTP verification loop with retry support
    while True:
        code = input("Enter the 6-digit code: ").strip()

        if code.lower() == "back":
            print("")
            return start_trial_flow()

        if not code:
            print("   Please enter the 6-digit code.")
            continue

        if code.isdigit() and len(code) != 6:
            print("❌ Please enter a valid 6-digit verification code.")
            continue

        if not code.isdigit():
            print("   Please enter the 6-digit code.")
            continue

        result = _complete_trial_registration(email, code, hw_id, nickname)
        if result == "success":
            return True
        if result == "terminal":
            return False
        # result == "retry" - offer retry options
        retry_action = _prompt_otp_retry(email, hw_id)
        if retry_action == "retry_code":
            print("")
            continue
        elif retry_action == "new_code":
            continue
        elif retry_action == "new_email":
            return start_trial_flow()
        else:
            return False


def _handle_otp_response(data: dict, email: str) -> bool | None:
    """
    Handle the OTP response statuses.
    Returns True/False for terminal states, None if OTP was sent and should continue.
    """
    status = data.get("status")

    if status == "already_paid":
        print("\033[2K\r🍋 You already have a paid license! Switching to activation flow...")
        return False

    if status == "trial_expired":
        print("\033[2K\r")
        print(f"⚠️  {data.get('message', 'Your trial has expired.')}")
        if show_trial_expired_prompt(email):
            return False
        sys.exit(0)

    if status == "trial_active_device_registered":
        trial_email = data.get("trial_email", email)
        if trial_email and trial_email.lower() != email.lower():
            print("\033[2K\r")
            print(f"⚠️  This device is already associated with: {trial_email}")
            print(f"   You entered: {email}")
            print("")
            print("   [1] Resume trial with original email")
            print("   [2] Cancel")
            print("")
            while True:
                choice = input("Enter choice [1/2]: ").strip()
                if choice == "1":
                    _restore_active_trial(data, trial_email)
                    return True
                elif choice == "2":
                    print("Goodbye!")
                    sys.exit(0)
                else:
                    print("   Please enter 1 or 2.")
        _restore_active_trial(data, email)
        return True

    if status == "machine_trial_expired":
        print("\033[2K\r")
        print(f"⚠️  {data.get('message', 'This device has already used its free trial.')}")
        prev_email = data.get("previous_email", "")
        if prev_email:
            print(f"   Previously registered with: {prev_email}")
        if show_trial_expired_prompt(prev_email or email):
            return False
        sys.exit(0)

    if status == "machine_trial_active":
        print("\033[2K\r")
        trial_email = data.get("trial_email", "")
        print(f"🍋 This device already has an active trial!")
        if trial_email:
            print(f"   Registered with: {trial_email}")
        print("   Run 'zest' again to continue using your trial.")
        sys.exit(0)

    if status == "otp_sent":
        return None  # Continue with OTP verification

    return None


def _restore_active_trial(data: dict, email: str):
    """Restore an active trial that was already registered on this device."""
    print("\033[2K\r")
    trial_email = data.get("trial_email", email)
    nickname = data.get("device_nickname", "this device")
    expires_at = data.get("trial_expires_at")
    days = data.get("days_remaining", 0)
    hours = data.get("hours_remaining", 0)
    minutes = data.get("minutes_remaining", 0)

    config = load_config()
    config["trial"] = {
        "email": trial_email,
        "is_trial": True,
        "trial_expires_at": expires_at,
        "trial_last_checked": time.time(),
        "device_nickname": nickname
    }
    save_config(config)

    print(f"🍋 Welcome back! Your trial is still active.")
    print(f"   Email: {trial_email}")
    print(f"   Device: \"{nickname}\"")
    if days > 0:
        print(f"   Time remaining: {days} days")
    elif hours > 0:
        print(f"   Time remaining: {hours} hours")
    elif minutes > 0:
        print(f"   Time remaining: {minutes} minutes")
    print("   Just a moment...")


def _complete_trial_registration(email: str, code: str, hw_id: str, nickname: str) -> str:
    """
    Complete trial registration after OTP verification.
    Returns: "success", "retry" (for OTP errors), or "terminal" (for non-retryable states)
    """
    print(f"\n\033[2K\r🌶️ Starting trial...", end="", flush=True)
    try:
        trial_res = requests.post(
            f"{API_BASE}/start_trial",
            json={
                "email": email,
                "otp_code": code,
                "device_id": hw_id,
                "device_name": nickname
            },
            timeout=15
        )

        if trial_res.status_code == 200:
            data = trial_res.json()
            status = data.get("status")

            if status == "already_paid":
                print("\033[2K\r🍋 You already have a paid license!")
                return "terminal"

            if status == "trial_expired":
                print("\033[2K\r")
                print("⚠️  Your trial has already expired.")
                if show_trial_expired_prompt(email):
                    return "terminal"
                sys.exit(0)

            if status in ["trial_started", "trial_active"]:
                _save_trial_config(email, nickname, data)
                _print_trial_success(status, data)
                return "success"

        # Check for OTP-related errors and show user-friendly message
        error_text = trial_res.text.lower()
        if "otp" in error_text or "code" in error_text or "expired" in error_text:
            print("\033[2K\r❌ Invalid or expired verification code.")
        else:
            print("\033[2K\r❌ Could not start trial. Please try again.")
        return "retry"

    except requests.exceptions.RequestException as e:
        print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}")
        return "retry"


def _save_trial_config(email: str, nickname: str, data: dict):
    """Save trial configuration to local config."""
    config = load_config()
    config["trial"] = {
        "email": email,
        "is_trial": True,
        "trial_expires_at": data.get("trial_expires_at"),
        "trial_last_checked": time.time(),
        "device_nickname": nickname
    }
    save_config(config)


def _print_trial_success(status: str, data: dict):
    """Print trial success message."""
    days = data.get("days_remaining", 0)
    hours = data.get("hours_remaining", 0)
    minutes = data.get("minutes_remaining", 0)

    print("\033[2K\r")
    action_word = "started" if status == "trial_started" else "continues"
    if days > 0:
        print(f"✅ Trial {action_word}! You have {days} days to try {PRODUCT_NAME}.")
    elif hours > 0:
        print(f"✅ Trial {action_word}! You have {hours} hours to try {PRODUCT_NAME}.")
    elif minutes > 0:
        print(f"✅ Trial {action_word}! You have {minutes} minutes to try {PRODUCT_NAME}.")
    else:
        print(f"✅ Trial {action_word}! Your trial is expiring soon.")
    print("   Just a moment...")


def _prompt_otp_retry(email: str, hw_id: str) -> str:
    """
    Prompt user for retry options after OTP verification failure.
    Returns: "retry_code", "new_code", "new_email", or "cancel"
    """
    print("")
    print("   [1] Re-enter the code")
    print("   [2] Send a new code")
    print("   [3] Use a different email")
    print("   [4] Cancel")
    print("")

    while True:
        choice = input("Enter choice [1/2/3/4]: ").strip()
        if choice == "1":
            return "retry_code"
        elif choice == "2":
            print(f"\n\033[2K\r🌶️ Sending new code to {email}...", end="", flush=True)
            try:
                otp_res = requests.post(
                    f"{API_BASE}/send_otp",
                    json={"email": email, "flow_type": "trial", "device_id": hw_id},
                    timeout=30
                )
                if otp_res.status_code == 200:
                    print("\033[2K\r📧 New verification code sent!\n")
                    return "new_code"
                else:
                    print(f"\033[2K\r❌ Error: {otp_res.text}")
                    print("   Please try again.")
            except requests.exceptions.RequestException as e:
                print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}")
                print("   Please try again.")
        elif choice == "3":
            return "new_email"
        elif choice == "4":
            return "cancel"
        else:
            print("   Please enter 1, 2, 3, or 4.")


def check_trial_license() -> bool:
    """
    Check if the user has an active trial.
    Returns True if trial is active, False if expired or no trial.
    """
    config = load_config()
    trial_data = config.get("trial")

    if not trial_data or not trial_data.get("is_trial"):
        return False

    email = trial_data.get("email")
    expires_at_str = trial_data.get("trial_expires_at")
    last_checked = trial_data.get("trial_last_checked", 0)
    current_time = time.time()

    if not expires_at_str:
        return False

    try:
        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        if now >= expires_at:
            return _handle_expired_trial(email, config)

        remaining = expires_at - now
        hours_remaining = int(remaining.total_seconds() / 3600)
        days_remaining = (hours_remaining + 23) // 24  # Ceiling division

        # Periodic server check
        if (current_time - last_checked) >= TRIAL_CHECK_INTERVAL:
            result = _check_trial_with_server(email, config, trial_data, current_time, days_remaining, hours_remaining)
            if result is not None:
                return result

        # Show daily reminder at 4, 3, 2, 1 days remaining (once per threshold)
        # Skip reminders during the first 24 hours (grace period)
        in_grace_period = remaining.total_seconds() > (4 * 86400)
        if 1 <= days_remaining <= 4 and not in_grace_period:
            last_reminder_day = trial_data.get("last_reminder_day", -1)
            if last_reminder_day != days_remaining:
                result = _show_trial_reminder(email, days_remaining, config, trial_data)
                if result is not None:
                    return result

        # Show warning if less than 1 day remaining (no prompt, just warning)
        elif days_remaining < 1:
            if hours_remaining > 0:
                print(f"⚠️  Trial expires in {hours_remaining} hours. Visit https://zestcli.com to purchase a license.")
            else:
                mins_remaining = int(remaining.total_seconds() / 60)
                print(f"⚠️  Trial expires in {mins_remaining} minutes. Visit https://zestcli.com to purchase a license.")

        return True

    except (ValueError, TypeError):
        pass

    return False


def _show_trial_reminder(email: str, days_remaining: int, config: dict, trial_data: dict) -> bool | None:
    """
    Show daily trial reminder and offer checkout.
    Returns True if user purchased, None to continue with normal flow.
    """
    day_word = "day" if days_remaining == 1 else "days"

    print("")
    print(f"⏰ Your {PRODUCT_NAME} trial expires in {days_remaining} {day_word}.")
    print("")
    print("   [1] Purchase a license now")
    print("   [2] Continue with trial")
    print("")

    while True:
        choice = input("Enter choice [1/2]: ").strip()
        if choice == "1":
            # Save reminder shown before starting checkout
            trial_data["last_reminder_day"] = days_remaining
            config["trial"] = trial_data
            save_config(config)

            # Start checkout flow
            if _start_reminder_checkout(email):
                return True
            return None
        elif choice == "2":
            # Save that we showed the reminder for this day threshold
            trial_data["last_reminder_day"] = days_remaining
            config["trial"] = trial_data
            save_config(config)
            print("")
            return None
        else:
            print("   Please enter 1 or 2.")


def _start_reminder_checkout(email: str) -> bool:
    """Start checkout flow from trial reminder."""
    print("")
    print(f"🍋 Opening checkout for {email}...")

    hw_id = get_hw_id()
    try:
        res = requests.post(
            f"{API_BASE}/get_checkout_url",
            json={"email": email, "device_id": hw_id},
            timeout=30
        )
        if res.status_code == 200:
            data = res.json()
            checkout_url = data.get("checkout_url")
            if checkout_url:
                print(f"\n🍋 Opening checkout in your browser...")
                print(f"   {checkout_url}")
                subprocess.run(["open", checkout_url], check=False)

                # Save pending checkout
                config = load_config()
                config["pending_checkout"] = {
                    "email": email,
                    "timestamp": time.time()
                }
                save_config(config)

                print("")
                print("   After payment, run a zest query to activate.")
                print("   For example: zest list all files in Downloads")
                return False
    except requests.exceptions.RequestException:
        pass

    print("❌ Could not open checkout. Visit https://zestcli.com to purchase a license.")
    return False


def _handle_expired_trial(email: str, config: dict) -> bool:
    """Handle an expired trial - delete model, check for pending checkout or show prompt."""
    _delete_model_file()
    pending_result = check_pending_checkout_and_activate()
    if pending_result is True:
        return True
    elif pending_result is False or pending_result in ("start_trial", "purchase"):
        del config["trial"]
        save_config(config)
        return False

    print("")
    if show_trial_expired_prompt(email):
        del config["trial"]
        save_config(config)
        return False
    sys.exit(0)


def _check_trial_with_server(email: str, config: dict, trial_data: dict, current_time: float,
                              days_remaining: int, hours_remaining: int) -> bool | None:
    """Check trial status with server during periodic refresh."""
    hw_id = get_hw_id()
    server_status = check_trial_status_with_server(email, hw_id)

    if not server_status:
        return None

    trial_data["trial_last_checked"] = current_time

    status = server_status.get("status")

    if status == "paid":
        print("🍋 Your license has been activated!")
        del config["trial"]
        config["license"] = {
            "email": email,
            "last_verified": current_time,
            "device_nickname": trial_data.get("device_nickname", "Device")
        }
        save_config(config)
        return True

    if status == "trial_expired":
        pending_result = check_pending_checkout_and_activate()
        if pending_result is True:
            return True
        elif pending_result is False or pending_result in ("start_trial", "purchase"):
            del config["trial"]
            save_config(config)
            return False

        print("")
        if show_trial_expired_prompt(email):
            del config["trial"]
            save_config(config)
            return False
        sys.exit(0)

    if status == "trial_active":
        trial_data["days_remaining"] = server_status.get("days_remaining", days_remaining)
        trial_data["hours_remaining"] = server_status.get("hours_remaining", hours_remaining)

    save_config(config)
    return None
