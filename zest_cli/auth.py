"""
Authentication orchestration for Zest CLI.
The main gatekeeper that checks licenses and routes to trial or paid activation flows.
"""

import sys
import subprocess
import time
import requests

from config import (
    API_BASE, PRODUCTS, LEASE_DURATION,
    load_config, save_config
)
from trial import (
    check_pending_checkout_and_activate,
    start_trial_flow,
    check_trial_license,
    get_hw_id
)
from activation import activate_paid_license


def authenticate(product: str) -> bool:
    """
    The Gatekeeper: Checks local 14-day lease or starts OTP flow for a product.
    Returns True if authenticated, exits on failure.
    """
    hw_id = get_hw_id()
    config = load_config()
    product_key = f"{product}_license"
    product_name = PRODUCTS[product]["name"]

    # 1. Check for local paid license lease
    license_data = config.get(product_key, {})
    if license_data:
        result = _check_paid_license(license_data, hw_id, product, config, product_key)
        if result is not None:
            return result

    # 2. Check for active trial
    if check_trial_license(product):
        return True

    # 3. Welcome/OTP Flow (For new users)
    return _handle_new_user_flow(product, product_name, config)


def _check_paid_license(license_data: dict, hw_id: str, product: str,
                        config: dict, product_key: str) -> bool | None:
    """Check if paid license is valid. Returns True/None on success, exits on failure."""
    email = license_data.get("email")
    last_verified = license_data.get("last_verified", 0)
    current_time = time.time()

    # If the 14-day lease is still valid, bypass network entirely
    if (current_time - last_verified) < LEASE_DURATION:
        return True

    # Lease expired: Attempt silent background refresh via heartbeat
    print("\033[K🌶\033[0m Refreshing license...", end="\r")
    try:
        res = requests.post(
            f"{API_BASE}/license_heartbeat",
            json={"email": email, "device_uuid": hw_id, "product": product},
            timeout=4
        )
        if res.status_code == 200:
            license_data["last_verified"] = current_time
            config[product_key] = license_data
            save_config(config)
            print("\033[K", end="")
            return True
        elif res.status_code == 403:
            _handle_heartbeat_403(res.text, product, config, product_key)
        elif res.status_code == 404:
            print("\n❌ License not found. Please re-purchase or contact support.")
            del config[product_key]
            save_config(config)
            sys.exit(1)
    except requests.exceptions.RequestException:
        # Offline Grace Period: Let them in if server is unreachable
        return True

    return None


def _handle_heartbeat_403(error_text: str, product: str, config: dict, product_key: str):
    """Handle 403 error from license heartbeat."""
    if "Device limit" in error_text or "not registered" in error_text:
        print(f"\n❌ {error_text}")
        print(f"   Run 'zest --uninstall --{product}' on another device to free a slot.")
    else:
        print(f"\n❌ License issue: {error_text}")
    del config[product_key]
    save_config(config)
    sys.exit(1)


def _handle_new_user_flow(product: str, product_name: str, config: dict) -> bool:
    """Handle flow for new users without existing license or trial."""
    # Check for pending checkout first (user may have just paid)
    pending_result = check_pending_checkout_and_activate(product)
    if pending_result is True:
        return True

    # Present choice between trial, paid account, and purchase
    _show_welcome_menu(product_name)

    while True:
        choice = input("Enter choice [1/2/3]: ").strip()

        if choice == "2":
            if start_trial_flow(product):
                return True
            print("\n🍋 Switching to paid account activation...")
            choice = "1"

        if choice == "3":
            _handle_purchase_flow(product, config)
            continue

        if choice == "1":
            break

        print("   Please enter 1, 2, or 3.")

    # Paid account activation flow
    print(f"\n🍋 Activation required for {product_name}.")
    email = input("Enter your purchase email: ").strip()

    if activate_paid_license(product, email):
        return True
    else:
        sys.exit(1)


def _show_welcome_menu(product_name: str):
    """Display the welcome menu."""
    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  Welcome to Zest {product_name}!")
    print("│")
    print("│  [1] I already have a paid account")
    print("│  [2] Start free trial (5 days)")
    print("│  [3] Purchase a license")
    print("└─────────────────────────────────────────────────┘")
    print("")


def _handle_purchase_flow(product: str, config: dict):
    """Handle the purchase flow - get checkout URL and open browser."""
    print("\n🍋 Purchase Zest license")
    purchase_email = input("Enter your email: ").strip()

    if not purchase_email or "@" not in purchase_email:
        print("❌ Please enter a valid email address.")
        return

    print("\n🌶\033[0m Getting checkout link...", end="\r")
    try:
        res = requests.post(
            f"{API_BASE}/get_checkout_url",
            json={"email": purchase_email, "product": product},
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
                # Save pending checkout state
                config["pending_checkout"] = {
                    "email": purchase_email,
                    "product": product,
                    "timestamp": time.time()
                }
                save_config(config)
                print("")
                print("   After payment, run a zest query to activate.")
                print("   For example: zest list all files in Downloads")
                sys.exit(0)
        print(f"\033[K❌ Could not get checkout URL. Visit https://zestcli.com")
    except requests.exceptions.RequestException as e:
        print(f"\033[K❌ Connection error: {e}. Visit https://zestcli.com")
