"""
Trial flow management for Zest CLI.
Handles trial start, expiration prompts, and pending checkout auto-activation.
"""

import sys
import subprocess
import time
import requests
from datetime import datetime, timezone

from config import (
    API_BASE, PRODUCTS, TRIAL_CHECK_INTERVAL,
    load_config, save_config
)


def get_hw_id():
    """Get the macOS Hardware UUID."""
    cmd = 'ioreg -d2 -c IOPlatformExpertDevice | awk -F"\\"" \'/IOPlatformUUID/{print $(NF-1)}\''
    return subprocess.check_output(cmd, shell=True).decode().strip()


def check_trial_status_with_server(email: str, product: str, device_id: str) -> dict | None:
    """Check trial status with the server. Returns status dict or None on error."""
    try:
        res = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": email, "product": product, "device_id": device_id},
            timeout=5
        )
        if res.status_code == 200:
            return res.json()
    except (requests.exceptions.RequestException, ValueError):
        pass
    return None


def check_pending_checkout_and_activate(product: str) -> bool | None:
    """
    Check if user has a pending checkout and attempt auto-activation.
    Returns True if activation succeeded, False if should proceed to normal flow,
    None if no pending checkout.
    """
    # Local import to avoid circular dependency
    from activation import activate_paid_license

    config = load_config()
    pending = config.get("pending_checkout")

    if not pending:
        return None

    pending_email = pending.get("email")
    pending_product = pending.get("product")
    pending_time = pending.get("timestamp", 0)

    # Only consider checkouts from the last 24 hours for the same product
    if pending_product != product or (time.time() - pending_time) > 86400:
        del config["pending_checkout"]
        save_config(config)
        return None

    hw_id = get_hw_id()

    print(f"\n🌶\033[0m Checking payment status...", end="\r")
    try:
        res = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": pending_email, "product": product, "device_id": hw_id},
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            if data.get("status") == "paid":
                print("\033[K✅ Payment confirmed! Starting activation...")
                del config["pending_checkout"]
                save_config(config)
                return activate_paid_license(product, pending_email)
            else:
                print("\033[K")
                print(f"🍋 Payment not yet received for {pending_email}.")
                print("   If you just completed payment, it may take a moment to process.")
                print("")
                print("   [1] Check again")
                print("   [2] Activate my license (requires email verification)")
                print("   [3] Exit")
                print("")
                while True:
                    choice = input("Enter choice [1/2/3]: ").strip()
                    if choice == "1":
                        return check_pending_checkout_and_activate(product)
                    elif choice == "2":
                        del config["pending_checkout"]
                        save_config(config)
                        return False
                    elif choice == "3":
                        print("👋 Goodbye!")
                        sys.exit(0)
                    else:
                        print("   Please enter 1, 2, or 3.")
    except requests.exceptions.RequestException:
        print("\033[K⚠️  Could not check payment status. Proceeding to activation.")

    del config["pending_checkout"]
    save_config(config)
    return False


def show_trial_expired_prompt(product: str, email: str) -> bool:
    """
    Show options when trial expires.
    Returns True if user wants to activate paid license, False otherwise.
    """
    product_name = PRODUCTS[product]["name"]
    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  Your free trial of {product_name} has expired.")
    print("│")
    print("│  [1] Purchase Zest")
    print("│  [2] I already paid - activate my license")
    print("│  [3] Exit")
    print("└─────────────────────────────────────────────────┘")
    print("")

    while True:
        choice = input("Enter choice [1/2/3]: ").strip()
        if choice == "1":
            print("\n🌶\033[0m Getting checkout link...", end="\r")
            try:
                res = requests.post(
                    f"{API_BASE}/get_checkout_url",
                    json={"email": email, "product": product},
                    timeout=10
                )
                if res.status_code == 200:
                    data = res.json()
                    checkout_url = data.get("checkout_url")
                    if checkout_url:
                        print("\033[K")
                        print(f"🍋 Opening checkout in your browser...")
                        print(f"   {checkout_url}")
                        subprocess.run(["open", checkout_url], check=False)
                        # Save pending checkout state for auto-activation on next run
                        config = load_config()
                        config["pending_checkout"] = {
                            "email": email,
                            "product": product,
                            "timestamp": time.time()
                        }
                        save_config(config)
                        print("")
                        print("   After payment, run a zest query to activate.")
                        print("   For example: zest list all files in Downloads")
                        return False
                print(f"\033[K❌ Could not get checkout URL (status {res.status_code}). Visit https://zestcli.com")
            except requests.exceptions.RequestException as e:
                print(f"\033[K❌ Connection error: {e}. Visit https://zestcli.com")
            return False
        elif choice == "2":
            return True
        elif choice == "3":
            print("👋 Goodbye!")
            sys.exit(0)
        else:
            print("   Please enter 1, 2, or 3.")


def start_trial_flow(product: str) -> bool:
    """
    Start a free trial for the product.
    Returns True if trial started successfully, False otherwise.
    """
    hw_id = get_hw_id()
    product_name = PRODUCTS[product]["name"]

    print(f"\n🍋 Start your free trial of {product_name}")

    # Email entry loop with retry on errors
    while True:
        email = input("Enter your email: ").strip()

        if not email or "@" not in email:
            print("❌ Please enter a valid email address.")
            continue

        print(f"🌶\033[0m Sending verification code to {email}...", end="\r")
        try:
            otp_res = requests.post(
                f"{API_BASE}/send_otp",
                json={"email": email, "product": product, "flow_type": "trial", "device_id": hw_id},
                timeout=10
            )
            if otp_res.status_code == 200:
                data = otp_res.json()
                result = _handle_otp_response(data, product, email)
                if result is not None:
                    return result
                # If result is None, OTP was sent successfully, break loop
                break
            else:
                print(f"\033[K❌ Error: {otp_res.text}")
                print("   Please try again or press Ctrl+C to cancel.")
                continue
        except requests.exceptions.RequestException as e:
            print(f"\033[K❌ Connection error: {e}")
            print("   Please try again or press Ctrl+C to cancel.")
            continue

    print("\033[K📧 Verification code sent!")
    code = input("Enter the 6-digit code: ").strip()

    print("")
    print("💻 Enter a nickname for this device")
    print("   (e.g., \"John's laptop\", \"Work MacBook\")")
    while True:
        nickname = input("   Nickname: ").strip()
        if nickname:
            break
        print("   ⚠️  Nickname is required.")

    return _complete_trial_registration(email, code, product, hw_id, nickname)


def _handle_otp_response(data: dict, product: str, email: str) -> bool | None:
    """
    Handle the OTP response statuses.
    Returns True/False for terminal states, None if OTP was sent and should continue.
    """
    status = data.get("status")

    if status == "already_paid":
        print("\033[K🍋 You already have a paid license! Switching to activation flow...")
        return False

    if status == "trial_expired":
        print("\033[K")
        print(f"⚠️  {data.get('message', 'Your trial has expired.')}")
        if show_trial_expired_prompt(product, email):
            return False
        sys.exit(0)

    if status == "trial_active_device_registered":
        _restore_active_trial(data, product, email)
        return True

    if status == "machine_trial_expired":
        print("\033[K")
        print(f"⚠️  {data.get('message', 'This device has already used its free trial.')}")
        prev_email = data.get("previous_email", "")
        if prev_email:
            print(f"   Previously registered with: {prev_email}")
        if show_trial_expired_prompt(product, prev_email or email):
            return False
        sys.exit(0)

    if status == "machine_trial_active":
        print("\033[K")
        trial_email = data.get("trial_email", "")
        print(f"🍋 This device already has an active trial!")
        if trial_email:
            print(f"   Registered with: {trial_email}")
        print("   Run 'zest' again to continue using your trial.")
        sys.exit(0)

    if status == "otp_sent":
        return None  # Continue with OTP verification

    return None


def _restore_active_trial(data: dict, product: str, email: str):
    """Restore an active trial that was already registered on this device."""
    print("\033[K")
    trial_email = data.get("trial_email", email)
    nickname = data.get("device_nickname", "this device")
    expires_at = data.get("trial_expires_at")
    days = data.get("days_remaining", 0)
    hours = data.get("hours_remaining", 0)
    minutes = data.get("minutes_remaining", 0)

    config = load_config()
    trial_key = f"{product}_trial"
    config[trial_key] = {
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


def _complete_trial_registration(email: str, code: str, product: str, hw_id: str, nickname: str) -> bool:
    """Complete trial registration after OTP verification."""
    product_name = PRODUCTS[product]["name"]

    print(f"\n🌶\033[0m Starting trial...", end="\r")
    try:
        trial_res = requests.post(
            f"{API_BASE}/start_trial",
            json={
                "email": email,
                "otp_code": code,
                "product": product,
                "device_id": hw_id,
                "device_name": nickname
            },
            timeout=10
        )

        if trial_res.status_code == 200:
            data = trial_res.json()
            status = data.get("status")

            if status == "already_paid":
                print("\033[K🍋 You already have a paid license!")
                return False

            if status == "trial_expired":
                print("\033[K")
                print("⚠️  Your trial has already expired.")
                if show_trial_expired_prompt(product, email):
                    return False
                sys.exit(0)

            if status in ["trial_started", "trial_active"]:
                _save_trial_config(email, product, nickname, data)
                _print_trial_success(status, data, product_name)
                return True

        print(f"\033[K❌ Could not start trial: {trial_res.text}")
        return False

    except requests.exceptions.RequestException as e:
        print(f"\033[K❌ Connection error: {e}")
        return False


def _save_trial_config(email: str, product: str, nickname: str, data: dict):
    """Save trial configuration to local config."""
    config = load_config()
    trial_key = f"{product}_trial"
    config[trial_key] = {
        "email": email,
        "is_trial": True,
        "trial_expires_at": data.get("trial_expires_at"),
        "trial_last_checked": time.time(),
        "device_nickname": nickname
    }
    save_config(config)


def _print_trial_success(status: str, data: dict, product_name: str):
    """Print trial success message."""
    days = data.get("days_remaining", 0)
    hours = data.get("hours_remaining", 0)
    minutes = data.get("minutes_remaining", 0)

    print("\033[K")
    action_word = "started" if status == "trial_started" else "continues"
    if days > 0:
        print(f"✅ Trial {action_word}! You have {days} days to try {product_name}.")
    elif hours > 0:
        print(f"✅ Trial {action_word}! You have {hours} hours to try {product_name}.")
    elif minutes > 0:
        print(f"✅ Trial {action_word}! You have {minutes} minutes to try {product_name}.")
    else:
        print(f"✅ Trial {action_word}! Your trial is expiring soon.")
    print("   Just a moment...")


def check_trial_license(product: str) -> bool:
    """
    Check if the user has an active trial for this product.
    Returns True if trial is active, False if expired or no trial.
    """
    config = load_config()
    trial_key = f"{product}_trial"
    trial_data = config.get(trial_key)

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
            return _handle_expired_trial(product, email, config, trial_key)

        remaining = expires_at - now
        hours_remaining = int(remaining.total_seconds() / 3600)
        days_remaining = hours_remaining // 24

        # Periodic server check
        if (current_time - last_checked) >= TRIAL_CHECK_INTERVAL:
            result = _check_trial_with_server(product, email, config, trial_key, trial_data, current_time, days_remaining, hours_remaining)
            if result is not None:
                return result

        # Show warning if trial expiring soon
        if days_remaining <= 1:
            if hours_remaining > 0:
                print(f"⚠️  Trial expires in {hours_remaining} hours. Visit https://zestcli.com to purchase.")
            else:
                mins_remaining = int(remaining.total_seconds() / 60)
                print(f"⚠️  Trial expires in {mins_remaining} minutes. Visit https://zestcli.com to purchase.")

        return True

    except (ValueError, TypeError):
        pass

    return False


def _handle_expired_trial(product: str, email: str, config: dict, trial_key: str) -> bool:
    """Handle an expired trial - check for pending checkout or show prompt."""
    pending_result = check_pending_checkout_and_activate(product)
    if pending_result is True:
        return True
    elif pending_result is False:
        del config[trial_key]
        save_config(config)
        return False

    print("")
    if show_trial_expired_prompt(product, email):
        del config[trial_key]
        save_config(config)
        return False
    sys.exit(0)


def _check_trial_with_server(product: str, email: str, config: dict, trial_key: str,
                              trial_data: dict, current_time: float,
                              days_remaining: int, hours_remaining: int) -> bool | None:
    """Check trial status with server during periodic refresh."""
    hw_id = get_hw_id()
    server_status = check_trial_status_with_server(email, product, hw_id)

    if not server_status:
        return None

    trial_data["trial_last_checked"] = current_time

    status = server_status.get("status")

    if status == "paid":
        print("🍋 Your license has been activated!")
        del config[trial_key]
        config[f"{product}_license"] = {
            "email": email,
            "last_verified": current_time,
            "device_nickname": trial_data.get("device_nickname", "Device")
        }
        save_config(config)
        return True

    if status == "trial_expired":
        pending_result = check_pending_checkout_and_activate(product)
        if pending_result is True:
            return True
        elif pending_result is False:
            del config[trial_key]
            save_config(config)
            return False

        print("")
        if show_trial_expired_prompt(product, email):
            del config[trial_key]
            save_config(config)
            return False
        sys.exit(0)

    if status == "trial_active":
        trial_data["days_remaining"] = server_status.get("days_remaining", days_remaining)
        trial_data["hours_remaining"] = server_status.get("hours_remaining", hours_remaining)

    save_config(config)
    return None
