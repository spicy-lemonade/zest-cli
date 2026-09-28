"""
Authentication orchestration for Zest CLI.
The main gatekeeper that checks licenses and routes to trial or paid activation flows.
"""

import sys
import subprocess
import time
import requests

from config import (
    API_BASE, PRODUCT_NAME, LEASE_DURATION,
    load_config, save_config, format_connection_error
)
from trial import (
    check_pending_checkout_and_activate,
    start_trial_flow,
    check_trial_license,
    get_hw_id
)
from activation import activate_paid_license


def authenticate() -> bool:
    """
    The Gatekeeper: Checks local 14-day lease or starts OTP flow.
    Returns True if authenticated, exits on failure.
    """
    hw_id = get_hw_id()
    config = load_config()

    # 1. Check for local paid license lease
    license_data = config.get("license", {})
    if license_data:
        result = _check_paid_license(license_data, hw_id, config)
        if result is not None:
            return result

    # 2. Check for active trial
    if check_trial_license():
        return True

    # 3. Welcome/OTP Flow (For new users)
    return _handle_new_user_flow(config)


def _check_paid_license(license_data: dict, hw_id: str, config: dict) -> bool | None:
    """Check if paid license is valid. Returns True/None on success, exits on failure."""
    email = license_data.get("email")
    last_verified = license_data.get("last_verified", 0)
    current_time = time.time()

    # If the 14-day lease is still valid, bypass network entirely
    if (current_time - last_verified) < LEASE_DURATION:
        return True

    # Lease expired: Attempt silent background refresh via heartbeat
    print("\033[2K\r🌶️ Refreshing license...", end="", flush=True)
    try:
        res = requests.post(
            f"{API_BASE}/license_heartbeat",
            json={"email": email, "device_uuid": hw_id},
            timeout=4
        )
        if res.status_code == 200:
            license_data["last_verified"] = current_time
            config["license"] = license_data
            save_config(config)
            print("\033[2K\r", end="")
            return True
        elif res.status_code == 403:
            _handle_heartbeat_403(res.text, config)
        elif res.status_code == 404:
            print("\n❌ License not found. Please re-purchase or contact support.")
            del config["license"]
            save_config(config)
            sys.exit(1)
    except requests.exceptions.RequestException:
        # Offline Grace Period: Let them in if server is unreachable
        return True

    return None


def _handle_heartbeat_403(error_text: str, config: dict):
    """Handle 403 error from license heartbeat."""
    if "Device limit" in error_text or "not registered" in error_text:
        print(f"\n❌ {error_text}")
        print(f"   Run 'zest --uninstall' on another device to free a slot.")
    else:
        print(f"\n❌ License issue: {error_text}")
    del config["license"]
    save_config(config)
    sys.exit(1)


def _handle_new_user_flow(config: dict) -> bool:
    """Handle flow for new users without existing license or trial."""
    # Check for pending checkout first (user may have just paid)
    pending_result = check_pending_checkout_and_activate()
    if pending_result is True:
        return True
    if pending_result == "start_trial":
        if start_trial_flow():
            return True
        print("\n🍋 Switching to paid account activation...")
        return _activate_paid_account()
    if pending_result == "purchase":
        config = load_config()
        _handle_purchase_flow(config)

    # Present choice between trial, paid account, and purchase
    _show_welcome_menu()

    while True:
        choice = input("Enter choice [1/2/3/4]: ").strip()

        if choice == "2":
            if start_trial_flow():
                return True
            print("\n🍋 Switching to paid account activation...")
            choice = "1"

        if choice == "3":
            _handle_purchase_flow(config)
            continue

        if choice == "4":
            print("👋 Goodbye!")
            sys.exit(0)

        if choice == "1":
            break

        print("   Please enter 1, 2, 3, or 4.")

    return _activate_paid_account()


def _activate_paid_account() -> bool:
    """Prompt for email and activate a paid license."""
    print(f"\n🍋 Activation required for {PRODUCT_NAME}.")
    email = input("Enter your purchase email: ").strip()

    if activate_paid_license(email):
        return True
    else:
        sys.exit(1)


def _show_welcome_menu():
    """Display the welcome menu."""
    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  Welcome to {PRODUCT_NAME}!")
    print("│")
    print("│  [1] I already have a paid account")
    print("│  [2] Start free trial (5 days)")
    print("│  [3] Purchase a license")
    print("│  [4] Exit")
    print("└─────────────────────────────────────────────────┘")
    print("")


def _handle_purchase_flow(config: dict):
    """Handle the purchase flow - get checkout URL and open browser."""
    print("\n🍋 Purchase Zest license")
    purchase_email = input("Enter your email: ").strip()

    if not purchase_email or "@" not in purchase_email:
        print("❌ Please enter a valid email address.")
        return

    confirm_email = input("Confirm your email: ").strip()
    if purchase_email != confirm_email:
        print("❌ Emails do not match. Please try again.")
        return

    print("\n\033[2K\r🌶️ Getting checkout link...", end="", flush=True)
    try:
        res = requests.post(
            f"{API_BASE}/get_checkout_url",
            json={"email": purchase_email},
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
                # Save pending checkout state
                config["pending_checkout"] = {
                    "email": purchase_email,
                    "timestamp": time.time()
                }
                save_config(config)
                print("")
                print("   After payment, run a zest query to activate.")
                print("   For example: zest list all files in Downloads")
                sys.exit(0)
        print(f"\033[2K\r❌ Could not get checkout URL. Visit https://zestcli.com")
    except requests.exceptions.RequestException as e:
        print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}. Visit https://zestcli.com")
