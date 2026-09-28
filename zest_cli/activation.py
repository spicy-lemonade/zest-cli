"""
Paid license activation, logout, and uninstall for Zest CLI.
"""

import os
import subprocess
import time
import json
import requests

from config import (
    API_BASE, PRODUCT_NAME, ZEST_DIR,
    load_config, save_config, format_connection_error
)
from trial import get_hw_id


def activate_paid_license(email: str) -> bool:
    """
    Activate a paid license for a user. Handles OTP and device registration.
    Returns True if activation succeeded.
    """
    config = load_config()
    hw_id = get_hw_id()

    # First check if license exists
    print(f"\033[2K\r🌶️ Checking license for {email}...", end="", flush=True)
    try:
        check_res = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": email, "device_id": hw_id},
            timeout=10
        )
        if check_res.status_code == 200:
            data = check_res.json()
            if data.get("status") != "paid":
                print("\033[2K\r")
                print(f"❌ No license found for {email}.")
                print("   Visit https://zestcli.com to purchase a license.")
                return False
        else:
            print("\033[2K\r")
            print(f"❌ No license found for {email}.")
            print("   Visit https://zestcli.com to purchase a license.")
            return False
    except requests.exceptions.RequestException as e:
        print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}")
        return False

    # License exists, send OTP
    print(f"\033[2K\r🌶️ Sending code to {email}...", end="", flush=True)
    try:
        otp_res = requests.post(
            f"{API_BASE}/send_otp",
            json={"email": email},
            timeout=30
        )
        if otp_res.status_code != 200:
            print(f"\033[2K\r❌ Error: {otp_res.text}")
            return False
    except Exception as e:
        print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}")
        return False

    print("\033[2K\r📧 Code sent!")
    while True:
        code = input("Enter the 6-digit code: ").strip()
        if not code:
            print("   Please enter the 6-digit code.")
            continue
        if code.isdigit() and len(code) != 6:
            print("❌ Please enter a valid 6-digit verification code.")
            continue
        if not code.isdigit():
            print("   Please enter the 6-digit code.")
            continue
        break

    # Check for existing nickname from trial data
    nickname = _get_existing_nickname(config, email, hw_id)

    if nickname:
        print(f"\n💻 Using device nickname: \"{nickname}\"")
    else:
        nickname = _prompt_for_nickname()

    # Verify OTP and register device
    return _register_device(email, code, hw_id, nickname, config)


def _get_existing_nickname(config: dict, email: str, hw_id: str) -> str | None:
    """Get existing nickname from local config or backend."""
    # Check local config first
    trial_data = config.get("trial", {})
    existing_nickname = trial_data.get("device_nickname")

    if existing_nickname:
        return existing_nickname

    # Check backend for trial nickname
    try:
        trial_check = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": email, "device_id": hw_id},
            timeout=15
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


def _register_device(email: str, code: str, hw_id: str, nickname: str, config: dict) -> bool:
    """Register device with the backend."""
    verify_res = requests.post(
        f"{API_BASE}/verify_otp_and_register",
        json={
            "email": email,
            "otp": code,
            "device_uuid": hw_id,
            "device_nickname": nickname
        }
    )

    if verify_res.status_code == 200:
        _save_license_config(config, email, nickname)
        print(f"✅ Success! Device \"{nickname}\" linked. Just a moment...")
        return True

    if verify_res.status_code == 403:
        return _handle_device_limit(verify_res, email, hw_id, nickname, config)

    print(f"❌ Activation failed: {verify_res.text}")
    return False


def _save_license_config(config: dict, email: str, nickname: str):
    """Save license configuration after successful activation."""
    config["license"] = {
        "email": email,
        "last_verified": time.time(),
        "device_nickname": nickname
    }
    if "trial" in config:
        del config["trial"]
    if "pending_checkout" in config:
        del config["pending_checkout"]
    save_config(config)


def _handle_device_limit(verify_res, email: str, hw_id: str, nickname: str, config: dict) -> bool:
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
                    return _replace_device(devices[choice_num - 1], email, hw_id, nickname, config)
                elif choice_num == len(devices) + 1:
                    print("❌ Cancelled.")
                    return False
            print(f"   Please enter a number between 1 and {len(devices) + 1}.")

    except (json.JSONDecodeError, ValueError):
        print(f"❌ Activation failed: {verify_res.text}")
        return False


def _replace_device(old_device: dict, email: str, hw_id: str, nickname: str, config: dict) -> bool:
    """Replace an existing device with the new one."""
    print(f"\n\033[2K\r🌶️ Replacing \"{old_device['nickname']}\"...", end="", flush=True)
    replace_res = requests.post(
        f"{API_BASE}/replace_device",
        json={
            "email": email,
            "old_device_uuid": old_device["uuid"],
            "new_device_uuid": hw_id,
            "new_device_nickname": nickname
        },
        timeout=10
    )

    if replace_res.status_code == 200:
        _save_license_config(config, email, nickname)
        print(f"\033[2K\r✅ Device \"{nickname}\" registered, replacing \"{old_device['nickname']}\".")
        return True

    print(f"\033[2K\r❌ Failed to replace device: {replace_res.text}")
    return False


def handle_logout(remote: bool = False):
    """
    Log out - removes license but keeps model files.
    If remote=True, allows logging out any registered device (requires OTP).
    """
    config = load_config()
    hw_id = get_hw_id()

    if remote:
        handle_remote_logout()
        return

    license_data = config.get("license")

    if not license_data:
        print("🍋 Not logged in on this device.")
        print("   Use --logout --remote to log out a device remotely.")
        return

    email = license_data.get("email")
    nickname = license_data.get("device_nickname", "this device")
    if email:
        _deregister_device_from_server(email, hw_id, nickname)

    del config["license"]
    save_config(config)
    print("🍋 Logout complete. Model files kept on disk.")
    print("   Use --uninstall to also remove model files.")


def _deregister_device_from_server(email: str, hw_id: str, nickname: str):
    """Deregister a device from the server."""
    print(f"\033[2K\r🌶️ Deregistering \"{nickname}\"...", end="", flush=True)
    try:
        res = requests.post(
            f"{API_BASE}/deregister_device",
            json={"email": email, "device_uuid": hw_id},
            timeout=10
        )
        if res.status_code == 200:
            print(f"\033[2K\r🍋 \"{nickname}\" deregistered from your license.")
        else:
            print(f"\033[2K\r⚠️  Could not deregister: {res.text}")
    except requests.exceptions.RequestException:
        print(f"\033[2K\r⚠️  Could not reach server. Device may still be registered.")


def handle_remote_logout():
    """Remote logout: deregister any device (not just the current one)."""
    print("🍋 Remote Device Logout")
    print("   This lets you deregister any device from your license.")
    print("")

    email = input("Enter your purchase email: ").strip()
    if not email:
        print("❌ Email is required.")
        return

    # Send OTP
    print(f"\n\033[2K\r🌶️ Sending verification code to {email}...", end="", flush=True)
    try:
        otp_res = requests.post(
            f"{API_BASE}/send_otp",
            json={"email": email},
            timeout=30
        )
        if otp_res.status_code != 200:
            print(f"\033[2K\r❌ Error: {otp_res.text}")
            return
    except requests.exceptions.RequestException as e:
        print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}")
        return

    print("\033[2K\r📧 Verification code sent!")
    while True:
        code = input("Enter the 6-digit code: ").strip()
        if not code:
            print("   Please enter the 6-digit code.")
            continue
        if code.isdigit() and len(code) != 6:
            print("❌ Please enter a valid 6-digit verification code.")
            continue
        if not code.isdigit():
            print("   Please enter the 6-digit code.")
            continue
        break

    devices = _fetch_device_list(email, code)
    if devices is None:
        return

    if not devices:
        print(f"🍋 No devices registered for {PRODUCT_NAME}.")
        return

    _display_and_deregister_device(devices, email)


def _fetch_device_list(email: str, code: str) -> list | None:
    """Fetch list of registered devices from server."""
    print(f"\n\033[2K\r🌶️ Fetching registered devices...", end="", flush=True)
    try:
        list_res = requests.post(
            f"{API_BASE}/list_devices",
            json={"email": email, "otp": code},
            timeout=10
        )
        if list_res.status_code != 200:
            print(f"\033[2K\r❌ Error: {list_res.text}")
            return None

        data = list_res.json()
        print("\033[2K\r")
        return data.get("devices", [])
    except requests.exceptions.RequestException as e:
        print(f"\033[2K\r❌ Connection error: {format_connection_error(e)}")
        return None
    except json.JSONDecodeError:
        print(f"\033[2K\r❌ Invalid response from server.")
        return None


def _display_and_deregister_device(devices: list, email: str):
    """Display device list and let user select one to deregister."""
    print(f"📱 Registered devices for {PRODUCT_NAME}:")
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
    _deregister_selected_device(selected_device, email, hw_id)


def _deregister_selected_device(device: dict, email: str, hw_id: str):
    """Deregister the selected device."""
    print(f"\n\033[2K\r🌶️ Deregistering \"{device['nickname']}\"...", end="", flush=True)
    try:
        dereg_res = requests.post(
            f"{API_BASE}/deregister_device",
            json={"email": email, "device_uuid": device["uuid"]},
            timeout=10
        )
        if dereg_res.status_code == 200:
            print(f"\033[2K\r🍋 \"{device['nickname']}\" deregistered.")

            # Clear local config if we deregistered current device
            if device["uuid"] == hw_id:
                config = load_config()
                if "license" in config:
                    del config["license"]
                    save_config(config)
                    print("   Local license data cleared.")
        else:
            print(f"\033[2K\r⚠️  Could not deregister: {dereg_res.text}")
    except requests.exceptions.RequestException:
        print(f"\033[2K\r⚠️  Could not reach server.")


def handle_uninstall():
    """
    Uninstall Zest - delegates to cleanup.sh for actual cleanup work.
    """
    cleanup_script = os.path.join(ZEST_DIR, "cleanup.sh")

    if os.path.exists(cleanup_script):
        try:
            subprocess.run([cleanup_script, "--uninstall"], check=False)
        except (subprocess.SubprocessError, OSError) as e:
            print(f"⚠️  Cleanup script error: {e}")
    else:
        print("❌ Cleanup script not found.")
        print("   Please reinstall Zest from the DMG to restore cleanup functionality.")
