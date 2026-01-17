"""
Paid license activation, logout, and uninstall for Zest CLI.
"""

import os
import sys
import subprocess
import time
import json
import requests

from config import (
    API_BASE, PRODUCTS, ZEST_DIR,
    load_config, save_config
)


def get_hw_id():
    """Get the macOS Hardware UUID."""
    cmd = 'ioreg -d2 -c IOPlatformExpertDevice | awk -F"\\"" \'/IOPlatformUUID/{print $(NF-1)}\''
    return subprocess.check_output(cmd, shell=True).decode().strip()


def activate_paid_license(product: str, email: str) -> bool:
    """
    Activate a paid license for a user. Handles OTP and device registration.
    Returns True if activation succeeded.
    """
    config = load_config()
    hw_id = get_hw_id()
    product_key = f"{product}_license"
    product_name = PRODUCTS[product]["name"]
    trial_key = f"{product}_trial"

    # Send OTP
    print(f"🌶\033[0m Sending code to {email}...", end="\r")
    try:
        otp_res = requests.post(
            f"{API_BASE}/send_otp",
            json={"email": email, "product": product}
        )
        if otp_res.status_code != 200:
            print(f"\n❌ Error: {otp_res.text}")
            return False
    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        return False

    print("\033[K📧 Code sent!")
    code = input("Enter the 6-digit code: ").strip()

    # Check for existing nickname from trial data
    nickname = _get_existing_nickname(config, trial_key, email, product, hw_id)

    if nickname:
        print(f"\n💻 Using device nickname: \"{nickname}\"")
    else:
        nickname = _prompt_for_nickname()

    # Verify OTP and register device
    return _register_device(email, code, hw_id, nickname, product, config, product_key, trial_key, product_name)


def _get_existing_nickname(config: dict, trial_key: str, email: str, product: str, hw_id: str) -> str | None:
    """Get existing nickname from local config or backend."""
    # Check local config first
    trial_data = config.get(trial_key, {})
    existing_nickname = trial_data.get("device_nickname")

    if existing_nickname:
        return existing_nickname

    # Check backend for trial nickname
    try:
        trial_check = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": email, "product": product, "device_id": hw_id},
            timeout=5
        )
        if trial_check.status_code == 200:
            trial_info = trial_check.json()
            return trial_info.get("device_nickname")
    except requests.exceptions.RequestException:
        pass

    return None


def _prompt_for_nickname() -> str:
    """Prompt user for device nickname."""
    print("")
    print("💻 Enter a nickname for this device")
    print("   (e.g., \"John's laptop\", \"Work MacBook\", \"Home iMac\")")
    while True:
        nickname = input("   Nickname: ").strip()
        if nickname:
            return nickname
        print("   ⚠️  Nickname is required. Please enter a name for this device.")


def _register_device(email: str, code: str, hw_id: str, nickname: str,
                     product: str, config: dict, product_key: str,
                     trial_key: str, product_name: str) -> bool:
    """Register device with the backend."""
    verify_res = requests.post(
        f"{API_BASE}/verify_otp_and_register",
        json={
            "email": email,
            "otp": code,
            "device_uuid": hw_id,
            "device_nickname": nickname,
            "product": product
        }
    )

    if verify_res.status_code == 200:
        _save_license_config(config, product_key, email, nickname, trial_key)
        print(f"✅ Success! Device \"{nickname}\" linked for {product_name}. Just a moment...")
        return True

    if verify_res.status_code == 403:
        return _handle_device_limit(verify_res, email, hw_id, nickname, product,
                                   config, product_key, trial_key)

    print(f"❌ Activation failed: {verify_res.text}")
    return False


def _save_license_config(config: dict, product_key: str, email: str, nickname: str, trial_key: str):
    """Save license configuration after successful activation."""
    config[product_key] = {
        "email": email,
        "last_verified": time.time(),
        "device_nickname": nickname
    }
    if trial_key in config:
        del config[trial_key]
    if "pending_checkout" in config:
        del config["pending_checkout"]
    save_config(config)


def _handle_device_limit(verify_res, email: str, hw_id: str, nickname: str,
                         product: str, config: dict, product_key: str, trial_key: str) -> bool:
    """Handle device limit reached error by offering to replace a device."""
    try:
        error_data = verify_res.json()
        if error_data.get("error") != "device_limit_reached":
            print(f"❌ Activation failed: {verify_res.text}")
            return False

        devices = error_data.get("devices", [])
        print(f"\n❌ Device limit reached ({len(devices)}/2).")
        print("   Which device would you like to de-authorize to make room for this one?")
        print("")
        for i, device in enumerate(devices, 1):
            print(f"   {i}) {device['nickname']}")
        print(f"   {len(devices) + 1}) Cancel")
        print("")

        while True:
            choice = input("   Enter choice: ").strip()
            if choice.isdigit():
                choice_num = int(choice)
                if 1 <= choice_num <= len(devices):
                    return _replace_device(devices[choice_num - 1], email, hw_id, nickname,
                                          product, config, product_key, trial_key)
                elif choice_num == len(devices) + 1:
                    print("❌ Cancelled.")
                    return False
            print(f"   Please enter a number between 1 and {len(devices) + 1}.")

    except (json.JSONDecodeError, ValueError):
        print(f"❌ Activation failed: {verify_res.text}")
        return False


def _replace_device(old_device: dict, email: str, hw_id: str, nickname: str,
                    product: str, config: dict, product_key: str, trial_key: str) -> bool:
    """Replace an existing device with the new one."""
    print(f"\n🌶\033[0m Replacing \"{old_device['nickname']}\"...", end="\r")
    replace_res = requests.post(
        f"{API_BASE}/replace_device",
        json={
            "email": email,
            "old_device_uuid": old_device["uuid"],
            "new_device_uuid": hw_id,
            "new_device_nickname": nickname,
            "product": product
        },
        timeout=10
    )

    if replace_res.status_code == 200:
        _save_license_config(config, product_key, email, nickname, trial_key)
        print(f"\033[K✅ Device \"{nickname}\" registered, replacing \"{old_device['nickname']}\".")
        return True

    print(f"\033[K❌ Failed to replace device: {replace_res.text}")
    return False


def handle_logout(product: str | None, remote: bool = False):
    """
    Log out from a product - removes license but keeps model files.
    If remote=True, allows logging out any registered device (requires OTP).
    """
    config = load_config()
    hw_id = get_hw_id()

    if product:
        products_to_logout = [product]
    else:
        licensed_products = [p for p in PRODUCTS.keys() if config.get(f"{p}_license")]
        if licensed_products:
            products_to_logout = licensed_products
        else:
            if not remote:
                print("🍋 Not logged in on this device.")
                print("   Use --logout --remote to log out a device remotely.")
                return
            products_to_logout = list(PRODUCTS.keys())

    if remote:
        handle_remote_logout(products_to_logout[0] if len(products_to_logout) == 1 else None)
        return

    any_logged_out = False

    for p in products_to_logout:
        product_key = f"{p}_license"
        license_data = config.get(product_key)

        if not license_data:
            if product:
                print(f"🍋 Not logged in for {PRODUCTS[p]['name']}.")
            continue

        email = license_data.get("email")
        nickname = license_data.get("device_nickname", "this device")
        if email:
            _deregister_device_from_server(email, hw_id, p, nickname)

        del config[product_key]
        any_logged_out = True

    save_config(config)
    if any_logged_out:
        print("🍋 Logout complete. Model files kept on disk.")
        print("   Use --uninstall to also remove model files.")


def _deregister_device_from_server(email: str, hw_id: str, product: str, nickname: str):
    """Deregister a device from the server."""
    print(f"🌶\033[0m Deregistering \"{nickname}\" from {PRODUCTS[product]['name']}...", end="\r")
    try:
        res = requests.post(
            f"{API_BASE}/deregister_device",
            json={"email": email, "device_uuid": hw_id, "product": product},
            timeout=10
        )
        if res.status_code == 200:
            print(f"\033[K🍋 \"{nickname}\" deregistered from {PRODUCTS[product]['name']} license.")
        else:
            print(f"\033[K⚠️  Could not deregister: {res.text}")
    except requests.exceptions.RequestException:
        print(f"\033[K⚠️  Could not reach server. Device may still be registered.")


def handle_remote_logout(product: str | None):
    """Remote logout: deregister any device (not just the current one)."""
    print("🍋 Remote Device Logout")
    print("   This lets you deregister any device from your license.")
    print("")

    email = input("Enter your purchase email: ").strip()
    if not email:
        print("❌ Email is required.")
        return

    if product is None:
        product = _prompt_for_product()
        if not product:
            return

    product_name = PRODUCTS[product]["name"]

    # Send OTP
    print(f"\n🌶\033[0m Sending verification code to {email}...", end="\r")
    try:
        otp_res = requests.post(
            f"{API_BASE}/send_otp",
            json={"email": email, "product": product},
            timeout=10
        )
        if otp_res.status_code != 200:
            print(f"\033[K❌ Error: {otp_res.text}")
            return
    except requests.exceptions.RequestException as e:
        print(f"\033[K❌ Connection error: {e}")
        return

    print("\033[K📧 Verification code sent!")
    code = input("Enter the 6-digit code: ").strip()
    if not code:
        print("❌ Code is required.")
        return

    devices = _fetch_device_list(email, code, product)
    if devices is None:
        return

    if not devices:
        print(f"🍋 No devices registered for {product_name}.")
        return

    _display_and_deregister_device(devices, product, product_name, email)


def _prompt_for_product() -> str | None:
    """Prompt user to select a product."""
    print("")
    print("Which product license?")
    print("   1. FP16 (Full Precision)")
    print("   2. Q5 (Quantized)")
    choice = input("Enter choice [1/2]: ").strip()
    if choice == "1":
        return "fp16"
    elif choice == "2":
        return "q5"
    else:
        print("❌ Invalid choice.")
        return None


def _fetch_device_list(email: str, code: str, product: str) -> list | None:
    """Fetch list of registered devices from server."""
    print(f"\n🌶\033[0m Fetching registered devices...", end="\r")
    try:
        list_res = requests.post(
            f"{API_BASE}/list_devices",
            json={"email": email, "otp": code, "product": product},
            timeout=10
        )
        if list_res.status_code != 200:
            print(f"\033[K❌ Error: {list_res.text}")
            return None

        data = list_res.json()
        print("\033[K")
        return data.get("devices", [])
    except requests.exceptions.RequestException as e:
        print(f"\033[K❌ Connection error: {e}")
        return None
    except json.JSONDecodeError:
        print(f"\033[K❌ Invalid response from server.")
        return None


def _display_and_deregister_device(devices: list, product: str, product_name: str, email: str):
    """Display device list and let user select one to deregister."""
    print(f"📱 Registered devices for {product_name}:")
    print("")
    hw_id = get_hw_id()
    for i, device in enumerate(devices, 1):
        is_current = " (this device)" if device["uuid"] == hw_id else ""
        print(f"   {i}) {device['nickname']}{is_current}")
    print(f"   {len(devices) + 1}) Cancel")
    print("")

    while True:
        choice = input("Which device to deregister? ").strip()
        if choice.isdigit():
            choice_num = int(choice)
            if choice_num == len(devices) + 1:
                print("❌ Cancelled.")
                return
            if 1 <= choice_num <= len(devices):
                break
        print(f"   Please enter a number between 1 and {len(devices) + 1}.")

    selected_device = devices[choice_num - 1]
    _deregister_selected_device(selected_device, email, product, product_name, hw_id)


def _deregister_selected_device(device: dict, email: str, product: str, product_name: str, hw_id: str):
    """Deregister the selected device."""
    print(f"\n🌶\033[0m Deregistering \"{device['nickname']}\"...", end="\r")
    try:
        dereg_res = requests.post(
            f"{API_BASE}/deregister_device",
            json={"email": email, "device_uuid": device["uuid"], "product": product},
            timeout=10
        )
        if dereg_res.status_code == 200:
            print(f"\033[K🍋 \"{device['nickname']}\" deregistered from {product_name}.")

            # Clear local config if we deregistered current device
            if device["uuid"] == hw_id:
                config = load_config()
                product_key = f"{product}_license"
                if product_key in config:
                    del config[product_key]
                    save_config(config)
                    print("   Local license data cleared.")
        else:
            print(f"\033[K⚠️  Could not deregister: {dereg_res.text}")
    except requests.exceptions.RequestException:
        print(f"\033[K⚠️  Could not reach server.")


def handle_uninstall(product: str | None):
    """
    Uninstall a product - delegates to cleanup.sh for actual cleanup work.
    """
    cleanup_script = os.path.join(ZEST_DIR, "cleanup.sh")

    cmd = [cleanup_script, "--uninstall"]
    if product == "fp16":
        cmd.append("--fp")
    elif product == "q5":
        cmd.append("--q5")

    if os.path.exists(cleanup_script):
        try:
            subprocess.run(cmd, check=False)
        except (subprocess.SubprocessError, OSError) as e:
            print(f"⚠️  Cleanup script error: {e}")
    else:
        print("❌ Cleanup script not found.")
        print("   Please reinstall Zest from the DMG to restore cleanup functionality.")


def handle_model_switch(product: str):
    """Switch active model preference."""
    if product not in PRODUCTS:
        print(f"❌ Invalid product. Use: --fp or --q5")
        sys.exit(1)

    model_path = PRODUCTS[product]["path"]
    if not os.path.exists(model_path):
        print(f"❌ {PRODUCTS[product]['name']} model not installed.")
        print(f"   Expected at: {model_path}")
        sys.exit(1)

    config = load_config()
    config["active_product"] = product
    save_config(config)
    print(f"✅ Switched to {PRODUCTS[product]['name']} model.")
