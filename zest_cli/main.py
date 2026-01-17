#!/usr/bin/env python3
"""
Retry
-----------
- Failed/rejected commands are stored in `failed_history` and excluded from future suggestions.
- Temperature starts at 0.2, increases by 0.15 per rejection (capped at 0.8) to encourage variety.
- Every 2 rejections, user is prompted for additional context to clarify intent.
- Temperature does not reset when user provides additional context, as we want continued exploration.

Execution
---------
- Success = return code 0 (not presence of stdout). Commands like `open`, `mkdir` produce no output.
- Expensive commands (find ~, grep -r /) trigger a warning before execution.

Input
-----
- Yes/no prompts require explicit responses (y/yes/yeah/ok or n/no/nah/nope).
- Queries over 20 words or with vague language ("help me", "urgent") trigger a quality warning.
"""

import sys
import os
import subprocess
import contextlib
import platform
import json
import requests
import time
import multiprocessing
import re
from datetime import datetime, timezone

# --- Configuration ---
VERSION = "1.0.0"
MODEL_VERSION = "1.0.0"  # Current model version bundled with this CLI
ZEST_DIR = os.path.expanduser("~/.zest")
MODEL_PATH_FP16 = os.path.join(ZEST_DIR, "qwen3_4b_fp16.gguf")
MODEL_PATH_Q5 = os.path.join(ZEST_DIR, "qwen3_4b_Q5_K_M.gguf")
API_BASE = "https://europe-west1-nl-cli-dev.cloudfunctions.net"  # TODO: Change back to nl-cli for production
CONFIG_DIR = os.path.expanduser("~/Library/Application Support/Zest")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")
LEASE_DURATION = 1209600  # 14 days in seconds
UPDATE_CHECK_INTERVAL = 1209600  # Check for updates every 2 weeks (same as lease)
TRIAL_CHECK_INTERVAL = 30  # TODO: Change back to 86400 (24 hours) for production

# Expected app bundle locations
APP_PATHS = {
    "fp16": "/Applications/Zest-FP16.app",
    "q5": "/Applications/Zest-Q5.app"
}

# Product configuration
PRODUCTS = {
    "fp16": {"path": MODEL_PATH_FP16, "name": "FP16 (Full Precision)"},
    "q5": {"path": MODEL_PATH_Q5, "name": "Q5 (Quantized)"}
}

# Response constants
AFFIRMATIVE = ("y", "yes", "yeah", "yep", "sure", "ok", "okay")
NEGATIVE = ("n", "no", "nah", "nope")


def load_config() -> dict:
    """Load configuration from disk."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def save_config(config: dict):
    """Save configuration to disk."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f)


def check_for_orphaned_installation(active_product: str) -> bool:
    """
    Check if app bundle has been deleted but files remain for the ACTIVE product only.
    Delegates to cleanup.sh for the actual cleanup work.
    Returns True if orphaned installation was detected and user chose to clean up.
    """
    config = load_config()
    cleanup_script = os.path.join(ZEST_DIR, "cleanup.sh")

    # Only check the active product, not all products
    product = active_product
    app_path = APP_PATHS[product]
    model_path = PRODUCTS[product]["path"]
    product_key = f"{product}_license"
    license_data = config.get(product_key)

    # Check for setup marker (created during first-run DMG setup)
    setup_marker = os.path.join(ZEST_DIR, f".{product}_setup_complete")
    # Also check for main.py in .zest (only copied during DMG first-run setup)
    main_py_marker = os.path.join(ZEST_DIR, "main.py")
    was_installed_via_dmg = os.path.exists(setup_marker) or os.path.exists(main_py_marker) or license_data

    # Trigger orphan cleanup if:
    # 1. Model exists
    # 2. App bundle is missing
    # 3. User went through DMG installation (has setup marker or license)
    if os.path.exists(model_path) and not os.path.exists(app_path) and was_installed_via_dmg:
        # Delegate to cleanup.sh which handles orphan detection and cleanup
        if os.path.exists(cleanup_script):
            try:
                result = subprocess.run([cleanup_script], check=False)
                return result.returncode == 0
            except (subprocess.SubprocessError, OSError):
                pass

        # Fallback message if cleanup.sh not available
        print(f"\n⚠️  Zest {PRODUCTS[product]['name']} app was removed from Applications.")
        print("   Model files still exist on this device.")
        print("")
        print("   Run 'zest --uninstall' to clean up.")
        return True

    return False


def download_model_with_progress(url: str, dest_path: str, total_size: int = 0) -> bool:
    """
    Download a model file with progress bar.
    Returns True if successful, False otherwise.
    """
    temp_path = dest_path + ".download"

    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()

        # Get total size from response if not provided
        if total_size == 0:
            total_size = int(response.headers.get("content-length", 0))

        downloaded = 0
        chunk_size = 1024 * 1024  # 1MB chunks

        # Ensure directory exists
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        with open(temp_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=chunk_size):
                if chunk:
                    f.write(chunk)
                    downloaded += len(chunk)

                    # Display progress
                    if total_size > 0:
                        percent = (downloaded / total_size) * 100
                        downloaded_mb = downloaded / (1024 * 1024)
                        total_mb = total_size / (1024 * 1024)
                        bar_width = 30
                        filled = int(bar_width * downloaded / total_size)
                        bar = "█" * filled + "░" * (bar_width - filled)
                        print(f"\r   [{bar}] {percent:.1f}% ({downloaded_mb:.0f}/{total_mb:.0f} MB)", end="", flush=True)
                    else:
                        downloaded_mb = downloaded / (1024 * 1024)
                        print(f"\r   Downloaded: {downloaded_mb:.0f} MB", end="", flush=True)

        print()  # New line after progress bar

        # Move temp file to final destination
        if os.path.exists(dest_path):
            os.remove(dest_path)
        os.rename(temp_path, dest_path)

        return True

    except requests.exceptions.RequestException as e:
        print(f"\n❌ Download failed: {e}")
        # Clean up temp file
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False
    except KeyboardInterrupt:
        print("\n❌ Download cancelled.")
        if os.path.exists(temp_path):
            os.remove(temp_path)
        return False


def get_model_version(product: str) -> str:
    """Get the installed model version for a product from config."""
    config = load_config()
    return config.get(f"{product}_model_version", MODEL_VERSION)


def set_model_version(product: str, version: str):
    """Save the installed model version for a product."""
    config = load_config()
    config[f"{product}_model_version"] = version
    save_config(config)


def check_for_updates(product: str) -> None:
    """
    Check for available updates. Only checks once per day.
    Displays notification and offers to download model updates.
    """
    config = load_config()
    last_check = config.get("last_update_check", 0)
    current_time = time.time()

    # Only check once per day
    if (current_time - last_check) < UPDATE_CHECK_INTERVAL:
        return

    current_model_version = get_model_version(product)

    try:
        res = requests.post(
            f"{API_BASE}/check_version",
            json={
                "current_version": VERSION,
                "current_model_version": current_model_version,
                "product": product
            },
            timeout=5
        )
        if res.status_code == 200:
            data = res.json()
            config["last_update_check"] = current_time
            save_config(config)

            # Check for CLI update
            if data.get("cli_update_available"):
                print("")
                print("┌─────────────────────────────────────────────────┐")
                print(f"│  🍋 CLI Update available: v{data.get('latest_cli_version', 'new')}")
                if data.get("update_message"):
                    msg = data.get("update_message")
                    print(f"│  {msg[:45]}")
                print(f"│  Download: {data.get('update_url', 'https://zestcli.com')}")
                print("└─────────────────────────────────────────────────┘")
                print("")

            # Check for model update
            if data.get("model_update_available"):
                latest_model_version = data.get("latest_model_version", "new")
                model_size = data.get("model_size_bytes", 0)
                size_gb = model_size / (1024 * 1024 * 1024) if model_size else 0

                print("")
                print("┌─────────────────────────────────────────────────┐")
                print(f"│  🍋 Model Update available: v{latest_model_version}")
                print(f"│  Product: {PRODUCTS[product]['name']}")
                if size_gb > 0:
                    print(f"│  Size: {size_gb:.1f} GB")
                print("└─────────────────────────────────────────────────┘")
                print("")

                choice = input("🍋 Download new model now? [y/n]: ").strip().lower()
                if choice in AFFIRMATIVE:
                    print("")
                    print(f"📥 Downloading {PRODUCTS[product]['name']} model...")
                    model_path = PRODUCTS[product]["path"]
                    download_url = data.get("model_download_url")

                    if download_url:
                        # Backup old model
                        backup_path = model_path + ".backup"
                        if os.path.exists(model_path):
                            os.rename(model_path, backup_path)

                        success = download_model_with_progress(
                            download_url,
                            model_path,
                            model_size
                        )

                        if success:
                            # Update stored model version
                            set_model_version(product, latest_model_version)
                            print(f"✅ Model updated to v{latest_model_version}")
                            # Remove backup
                            if os.path.exists(backup_path):
                                os.remove(backup_path)
                        else:
                            # Restore backup on failure
                            if os.path.exists(backup_path):
                                os.rename(backup_path, model_path)
                                print("   Restored previous model.")
                    else:
                        print("❌ No download URL available.")
                else:
                    print("   Skipping model update. Run 'zest --update' later to update.")

    except (requests.exceptions.RequestException, json.JSONDecodeError):
        # Silently fail - don't block user if update check fails
        pass


def get_active_product() -> str | None:
    """
    Determine which product to use.
    Priority: 1) User preference, 2) fp16 if available, 3) q5 if available
    Only considers products where the app bundle is installed (DMG mode).
    Returns None if no models are installed.
    """
    config = load_config()
    preferred = config.get("active_product")

    # If user has a preference and both model and app exist, use it
    if preferred:
        app_exists = os.path.exists(APP_PATHS.get(preferred, ""))
        model_exists = os.path.exists(PRODUCTS[preferred]["path"])
        if app_exists and model_exists:
            return preferred

    # Otherwise, prefer fp16 over q5 if available AND app is installed
    for product in ["fp16", "q5"]:
        app_exists = os.path.exists(APP_PATHS[product])
        model_exists = os.path.exists(PRODUCTS[product]["path"])
        if app_exists and model_exists:
            return product

    # Fallback: if no app bundle but model exists, still allow (dev/manual mode)
    if os.path.exists(MODEL_PATH_FP16):
        return "fp16"
    if os.path.exists(MODEL_PATH_Q5):
        return "q5"

    return None  # No models installed


def get_hw_id():
    """Captures the macOS Hardware UUID as per your spec."""
    cmd = 'ioreg -d2 -c IOPlatformExpertDevice | awk -F"\\"" \'/IOPlatformUUID/{print $(NF-1)}\''
    return subprocess.check_output(cmd, shell=True).decode().strip()


def check_trial_status_with_server(email: str, product: str, device_id: str) -> dict:
    """Check trial status with the server. Returns status dict or None on error."""
    try:
        res = requests.post(
            f"{API_BASE}/check_trial_status",
            json={"email": email, "product": product, "device_id": device_id},
            timeout=5
        )
        if res.status_code == 200:
            return res.json()
    except (requests.exceptions.RequestException, json.JSONDecodeError):
        pass
    return None


def show_trial_expired_prompt(product: str, email: str) -> bool:
    """
    Show options when trial expires.
    Returns True if user successfully activates a paid license, False otherwise.
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
                if data.get("status") == "already_paid":
                    print("\033[K🍋 You already have a paid license! Switching to activation flow...")
                    return False
                if data.get("status") == "trial_expired":
                    print("\033[K")
                    print(f"⚠️  {data.get('message', 'Your trial has expired.')}")
                    if show_trial_expired_prompt(product, email):
                        return False
                    sys.exit(0)
                if data.get("status") == "trial_active_device_registered":
                    # Device already registered on active trial - no OTP/nickname needed
                    print("\033[K")
                    # Use trial_email from response (may differ from entered email)
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
                    return True
                if data.get("status") == "machine_trial_expired":
                    print("\033[K")
                    print(f"⚠️  {data.get('message', 'This device has already used its free trial.')}")
                    prev_email = data.get("previous_email", "")
                    if prev_email:
                        print(f"   Previously registered with: {prev_email}")
                    if show_trial_expired_prompt(product, prev_email or email):
                        return False
                    sys.exit(0)
                if data.get("status") == "machine_trial_active":
                    print("\033[K")
                    trial_email = data.get("trial_email", "")
                    print(f"🍋 This device already has an active trial!")
                    if trial_email:
                        print(f"   Registered with: {trial_email}")
                    print("   Run 'zest' again to continue using your trial.")
                    sys.exit(0)
                if data.get("status") == "otp_sent":
                    # OTP sent successfully, break out of email loop
                    break
            else:
                # Server error - allow retry
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
                expires_at = data.get("trial_expires_at")
                days = data.get("days_remaining", 0)
                hours = data.get("hours_remaining", 0)
                minutes = data.get("minutes_remaining", 0)

                config = load_config()
                trial_key = f"{product}_trial"
                config[trial_key] = {
                    "email": email,
                    "is_trial": True,
                    "trial_expires_at": expires_at,
                    "trial_last_checked": time.time(),
                    "device_nickname": nickname
                }
                save_config(config)

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
                return True

        print(f"\033[K❌ Could not start trial: {trial_res.text}")
        return False

    except requests.exceptions.RequestException as e:
        print(f"\033[K❌ Connection error: {e}")
        return False


def check_trial_license(product: str) -> bool:
    """
    Check if the user has an active trial for this product.
    Returns True if trial is active (user can proceed), False if expired or no trial.
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

    if expires_at_str:
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)

            if now >= expires_at:
                print("")
                if show_trial_expired_prompt(product, email):
                    del config[trial_key]
                    save_config(config)
                    return False
                sys.exit(0)

            remaining = expires_at - now
            hours_remaining = int(remaining.total_seconds() / 3600)
            days_remaining = hours_remaining // 24

            if (current_time - last_checked) >= TRIAL_CHECK_INTERVAL:
                hw_id = get_hw_id()
                server_status = check_trial_status_with_server(email, product, hw_id)

                if server_status:
                    trial_data["trial_last_checked"] = current_time

                    if server_status.get("status") == "paid":
                        print("🍋 Your license has been activated!")
                        del config[trial_key]
                        config[f"{product}_license"] = {
                            "email": email,
                            "last_verified": current_time,
                            "device_nickname": trial_data.get("device_nickname", "Device")
                        }
                        save_config(config)
                        return True

                    if server_status.get("status") == "trial_expired":
                        print("")
                        if show_trial_expired_prompt(product, email):
                            del config[trial_key]
                            save_config(config)
                            return False
                        sys.exit(0)

                    if server_status.get("status") == "trial_active":
                        days_remaining = server_status.get("days_remaining", days_remaining)
                        hours_remaining = server_status.get("hours_remaining", hours_remaining)

                    save_config(config)

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


def authenticate(product: str):
    """The Gatekeeper: Checks local 14-day lease or starts OTP flow for a product."""
    hw_id = get_hw_id()
    config = load_config()
    product_key = f"{product}_license"
    model_path = PRODUCTS[product]["path"]
    product_name = PRODUCTS[product]["name"]

    # 1. Check for local lease for this product
    license_data = config.get(product_key, {})
    if license_data:
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
                error_text = res.text
                if "Device limit" in error_text or "not registered" in error_text:
                    print(f"\n❌ {error_text}")
                    print(f"   Run 'zest --uninstall --{product}' on another device to free a slot.")
                else:
                    print(f"\n❌ License issue: {error_text}")
                del config[product_key]
                save_config(config)
                sys.exit(1)
            elif res.status_code == 404:
                print("\n❌ License not found. Please re-purchase or contact support.")
                del config[product_key]
                save_config(config)
                sys.exit(1)
        except requests.exceptions.RequestException:
            # Offline Grace Period: Let them in if server is unreachable
            return True

    # 2. Welcome/OTP Flow (For new devices or expired/revoked licenses)

    # Present choice between trial and paid account
    print("")
    print("┌─────────────────────────────────────────────────┐")
    print(f"│  Welcome to Zest {product_name}!")
    print("│")
    print("│  [1] I already have a paid account")
    print("│  [2] Start free trial (5 days)")
    print("└─────────────────────────────────────────────────┘")
    print("")

    while True:
        choice = input("Enter choice [1/2]: ").strip()
        if choice == "2":
            if start_trial_flow(product):
                return True
            print("\n🍋 Switching to paid account activation...")
            choice = "1"
        if choice == "1":
            break
        print("   Please enter 1 or 2.")

    print(f"\n🍋 Activation required for {product_name}.")
    email = input("Enter your purchase email: ").strip()

    print(f"🌶\033[0m Sending code to {email}...", end="\r")
    try:
        otp_res = requests.post(
            f"{API_BASE}/send_otp",
            json={"email": email, "product": product}
        )
        if otp_res.status_code != 200:
            print(f"\n❌ Error: {otp_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        sys.exit(1)

    print("\033[K📧 Code sent!")
    code = input("Enter the 6-digit code: ").strip()

    # Check for existing nickname from trial data (for smooth trial-to-paid conversion)
    # First check local config
    trial_key = f"{product}_trial"
    trial_data = config.get(trial_key, {})
    existing_nickname = trial_data.get("device_nickname")

    # If not in local config, check backend for trial nickname
    if not existing_nickname:
        try:
            trial_check = requests.post(
                f"{API_BASE}/check_trial_status",
                json={"email": email, "product": product, "device_id": hw_id},
                timeout=5
            )
            if trial_check.status_code == 200:
                trial_info = trial_check.json()
                existing_nickname = trial_info.get("device_nickname")
        except requests.exceptions.RequestException:
            pass  # Ignore errors, will prompt for nickname

    if existing_nickname:
        # Reuse nickname from trial for frictionless conversion
        nickname = existing_nickname
        print(f"\n💻 Using device nickname: \"{nickname}\"")
    else:
        # Prompt for mandatory device nickname
        print("")
        print("💻 Enter a nickname for this device")
        print("   (e.g., \"John's laptop\", \"Work MacBook\", \"Home iMac\")")
        while True:
            nickname = input("   Nickname: ").strip()
            if nickname:
                break
            print("   ⚠️  Nickname is required. Please enter a name for this device.")

    # Final Verification and Device Registration
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
        config[product_key] = {
            "email": email,
            "last_verified": time.time(),
            "device_nickname": nickname
        }
        # Clear trial data after successful paid activation
        if trial_key in config:
            del config[trial_key]
        save_config(config)
        print(f"✅ Success! Device \"{nickname}\" linked for {product_name}. Just a moment...")
        return True
    elif verify_res.status_code == 403:
        # Check if device limit reached
        try:
            error_data = verify_res.json()
            if error_data.get("error") == "device_limit_reached":
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
                            old_device = devices[choice_num - 1]
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
                                config[product_key] = {
                                    "email": email,
                                    "last_verified": time.time(),
                                    "device_nickname": nickname
                                }
                                save_config(config)
                                print(f"\033[K✅ Device \"{nickname}\" registered, replacing \"{old_device['nickname']}\".")
                                return True
                            else:
                                print(f"\033[K❌ Failed to replace device: {replace_res.text}")
                                sys.exit(1)
                        elif choice_num == len(devices) + 1:
                            print("❌ Cancelled.")
                            sys.exit(0)
                    print(f"   Please enter a number between 1 and {len(devices) + 1}.")
        except (json.JSONDecodeError, requests.exceptions.JSONDecodeError, ValueError):
            # Server returned non-JSON response (plain text error)
            pass
        print(f"❌ Activation failed: {verify_res.text}")
        sys.exit(1)
    else:
        print(f"❌ Activation failed: {verify_res.text}")
        sys.exit(1)

# --- Query Validation ---

def check_query_quality(query: str) -> tuple[bool, int, bool, bool]:
    """Check if query is too long, vague, or likely shell-mangled."""
    word_count = len(query.split())

    # Suspiciously long queries often indicate shell expansion
    likely_shell_mangled = word_count > 100

    vague_indicators = [
        "help me", "urgent", "trouble", "problem",
        "boss", "deadline", "asap",
        "something like", "or something", "i think", "maybe", "probably",
        "i cant seem", "would you be able", "could you",
        "can you help", "im not sure", "i dont know"
    ]

    query_lower = query.lower()
    has_vague_language = any(indicator in query_lower for indicator in vague_indicators)

    is_good = word_count <= 20 and not has_vague_language and not likely_shell_mangled

    return is_good, word_count, has_vague_language, likely_shell_mangled


def is_expensive_command(command: str) -> tuple[bool, str | None]:
    """Check if a command might be slow or produce excessive output."""
    expensive_patterns = [
        ("find ~", "searching your entire home directory"),
        ("find /", "searching your entire computer"),
        ("grep -r ~", "searching all files in your home directory"),
        ("grep -r /", "searching all files on your computer"),
        ("du -a ~", "calculating size of everything in your home directory"),
        ("du -a /", "calculating size of everything on your computer"),
        ("find . -name", "searching this folder and all nested folders"),
        ("find . -type", "searching this folder and all nested folders"),
    ]

    for pattern, reason in expensive_patterns:
        if pattern in command:
            return True, reason

    return False, None


def clean_command_output(response: str) -> str:
    """
    Clean the model output to extract only the command.
    Handles ChatML tags, markdown, placeholders, and multi-line responses.
    """
    response = response.replace("<|im_end|>", "")
    response = response.replace("<|endoftext|>", "")
    response = response.replace("<|end_of_text|>", "")

    response = response.replace("```bash", "").replace("```sh", "").replace("```", "")

    response = re.sub(r"\[\[\[(.*?)\]\]\]", r"\1", response)
    response = re.sub(r"\[\[(.*?)\]\]", r"\1", response)
    response = re.sub(r"\[-(.*?)-\]", r"\1", response)

    response = " ".join(response.split())

    lines = [line.strip() for line in response.split("\n") if line.strip()]

    if len(lines) > 1:
        has_continuation = any(line.endswith("\\") for line in lines[:-1])
        has_heredoc = any(re.search(r"<<\s*\w+", line) for line in lines)
        has_pipe_continuation = any(line.endswith("|") for line in lines[:-1])

        second_line_is_explanation = (
            len(lines) > 1 and
            (lines[1][0].isupper() or
             any(lines[1].lower().startswith(word) for word in
                 ["this", "the", "it", "note:", "example:", "usage:"]))
        )

        if second_line_is_explanation:
            response = lines[0]
        elif has_continuation or has_heredoc or has_pipe_continuation:
            response = "\n".join(lines)
        else:
            response = lines[0]
    else:
        response = lines[0] if lines else ""

    response = response.replace("`", "").strip()

    return response


def get_os_type() -> str:
    """Get the operating system type for the system prompt."""
    system = platform.system()
    if system == "Darwin":
        return "macOS"
    elif system == "Linux":
        return "Linux"
    elif system == "Windows":
        return "Windows"
    return "Unix"


# --- AI & Execution Logic ---

@contextlib.contextmanager
def suppress_c_logs():
    stderr_fd = sys.stderr.fileno()
    saved_stderr_fd = os.dup(stderr_fd)
    try:
        with open(os.devnull, 'w') as devnull:
            os.dup2(devnull.fileno(), stderr_fd)
        yield
    finally:
        os.dup2(saved_stderr_fd, stderr_fd)
        os.close(saved_stderr_fd)


def load_model(product: str):
    """Load the LLM model with GPU acceleration fallback to CPU."""
    # Lazy import to speed up CLI startup for --help, --status, etc.
    from llama_cpp import Llama

    model_path = PRODUCTS[product]["path"]
    if not os.path.exists(model_path):
        sys.stderr.write(f"❌ Error: Model not found at {model_path}\n")
        sys.stderr.write("   Please ensure Zest is properly installed.\n")
        sys.exit(1)

    recommended_threads = max(1, multiprocessing.cpu_count() // 2)
    params = {
        "model_path": model_path,
        "n_ctx": 1024,
        "n_batch": 512,
        "n_threads": recommended_threads,
        "verbose": False
    }

    with suppress_c_logs():
        try:
            return Llama(**params, n_gpu_layers=-1)
        except Exception:
            sys.stderr.write("⚠️ GPU acceleration failed, falling back to CPU...\n")
            return Llama(**params, n_gpu_layers=0)

def generate_command(
    llm,
    query: str,
    history: list[tuple[str, str]] | None = None,
    base_temp: float = 0.2,
    temp_increment: int = 0,
    user_context: str | None = None,
    os_name: str | None = None
) -> str:
    """Generate a CLI command using the LLM with retry-aware temperature scaling."""
    if os_name is None:
        os_name = get_os_type()

    system_prompt = (
        f"You are a specialized CLI assistant for {os_name}. "
        f"Provide only the exact command requested. "
        f"Do not include placeholders, brackets, or explanations. "
        f"Output must be a valid, executable command."
    )

    system_part = f"<|im_start|>system\n{system_prompt}<|im_end|>\n"

    history_context = ""
    if history:
        tried_commands = [cmd for cmd, _ in history]
        history_context = "\n\nDo NOT suggest any of these commands (already tried and rejected):\n"
        for cmd in tried_commands[-5:]:
            history_context += f"- {cmd}\n"
        history_context += "\nProvide a DIFFERENT command."

    additional_context = ""
    if user_context:
        additional_context = f"\n\nAdditional context from user: {user_context}"

    prompt = f"{system_part}<|im_start|>user\n{query}{history_context}{additional_context}<|im_end|>\n<|im_start|>assistant\n"

    temp = min(base_temp + (temp_increment * 0.15), 0.8)

    output = llm(
        prompt,
        max_tokens=120,
        stop=["<|im_end|>", "```", "\n\n", "Try:", "Explanation:", "Instead:"],
        echo=False,
        temperature=temp
    )

    cmd = output["choices"][0]["text"].strip()

    return clean_command_output(cmd)


# --- User Interaction Helpers ---

def prompt_yes_no(message: str) -> bool:
    """
    Prompt user for yes/no input. Re-prompts on ambiguous input.
    Returns True for affirmative, False for negative.
    """
    while True:
        choice = input(message).lower().strip()
        if choice in AFFIRMATIVE:
            return True
        elif choice in NEGATIVE:
            return False
        else:
            print("   Please enter y or n.")


def prompt_for_context(user_context: str | None) -> tuple[str | None, bool]:
    """
    Prompt user for additional context.
    Returns (new_context, was_provided).
    """
    print("\n💡 Having trouble finding the right command?")
    context_input = input("💬 Add context to help? (or 'n' to skip): ").strip()
    if context_input and context_input.lower() not in NEGATIVE:
        return context_input, True
    return user_context, False

def handle_logout(product: str | None, remote: bool = False):
    """
    Log out from a product - removes license but keeps model files.
    If remote=True, allows logging out any registered device (requires OTP).
    Deregisters device from Firestore.
    """
    config = load_config()
    hw_id = get_hw_id()

    # Determine product to logout
    if product:
        products_to_logout = [product]
    else:
        # Check which products are licensed locally
        licensed_products = [p for p in PRODUCTS.keys() if config.get(f"{p}_license")]
        if licensed_products:
            products_to_logout = licensed_products
        else:
            # No local license - must use remote logout
            if not remote:
                print("🍋 Not logged in on this device.")
                print("   Use --logout --remote to log out a device remotely.")
                return
            products_to_logout = list(PRODUCTS.keys())

    # Remote logout flow
    if remote:
        handle_remote_logout(products_to_logout[0] if len(products_to_logout) == 1 else None)
        return

    any_logged_out = False

    for p in products_to_logout:
        product_key = f"{p}_license"
        license_data = config.get(product_key)

        if not license_data:
            if product:  # Only show if specific product requested
                print(f"🍋 Not logged in for {PRODUCTS[p]['name']}.")
            continue

        email = license_data.get("email")
        nickname = license_data.get("device_nickname", "this device")
        if email:
            print(f"🌶\033[0m Deregistering \"{nickname}\" from {PRODUCTS[p]['name']}...", end="\r")
            try:
                res = requests.post(
                    f"{API_BASE}/deregister_device",
                    json={"email": email, "device_uuid": hw_id, "product": p},
                    timeout=10
                )
                if res.status_code == 200:
                    print(f"\033[K🍋 \"{nickname}\" deregistered from {PRODUCTS[p]['name']} license.")
                else:
                    print(f"\033[K⚠️  Could not deregister: {res.text}")
            except requests.exceptions.RequestException:
                print(f"\033[K⚠️  Could not reach server. Device may still be registered.")

        del config[product_key]
        any_logged_out = True

    save_config(config)
    if any_logged_out:
        print("🍋 Logout complete. Model files kept on disk.")
        print("   Use --uninstall to also remove model files.")


def handle_remote_logout(product: str | None):
    """
    Remote logout: deregister any device (not just the current one).
    Requires OTP verification for security.
    """
    print("🍋 Remote Device Logout")
    print("   This lets you deregister any device from your license.")
    print("")

    email = input("Enter your purchase email: ").strip()
    if not email:
        print("❌ Email is required.")
        return

    # Determine product
    if product is None:
        print("")
        print("Which product license?")
        print("   1. FP16 (Full Precision)")
        print("   2. Q5 (Quantized)")
        choice = input("Enter choice [1/2]: ").strip()
        if choice == "1":
            product = "fp16"
        elif choice == "2":
            product = "q5"
        else:
            print("❌ Invalid choice.")
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

    # Get device list
    print(f"\n🌶\033[0m Fetching registered devices...", end="\r")
    try:
        list_res = requests.post(
            f"{API_BASE}/list_devices",
            json={"email": email, "otp": code, "product": product},
            timeout=10
        )
        if list_res.status_code != 200:
            print(f"\033[K❌ Error: {list_res.text}")
            return

        data = list_res.json()
        devices = data.get("devices", [])
    except requests.exceptions.RequestException as e:
        print(f"\033[K❌ Connection error: {e}")
        return
    except json.JSONDecodeError:
        print(f"\033[K❌ Invalid response from server.")
        return

    print("\033[K")

    if not devices:
        print(f"🍋 No devices registered for {product_name}.")
        return

    # Display devices
    print(f"📱 Registered devices for {product_name}:")
    print("")
    hw_id = get_hw_id()
    for i, device in enumerate(devices, 1):
        is_current = " (this device)" if device["uuid"] == hw_id else ""
        print(f"   {i}) {device['nickname']}{is_current}")
    print(f"   {len(devices) + 1}) Cancel")
    print("")

    # Get selection
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

    # Deregister selected device
    print(f"\n🌶\033[0m Deregistering \"{selected_device['nickname']}\"...", end="\r")
    try:
        dereg_res = requests.post(
            f"{API_BASE}/deregister_device",
            json={
                "email": email,
                "device_uuid": selected_device["uuid"],
                "product": product
            },
            timeout=10
        )
        if dereg_res.status_code == 200:
            print(f"\033[K🍋 \"{selected_device['nickname']}\" deregistered from {product_name}.")

            # If we deregistered the current device, clear local config
            if selected_device["uuid"] == hw_id:
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
    cleanup.sh handles: deregistration, model deletion, app removal, config cleanup.
    """
    cleanup_script = os.path.join(ZEST_DIR, "cleanup.sh")

    # Build the command for cleanup.sh
    cmd = [cleanup_script, "--uninstall"]
    if product == "fp16":
        cmd.append("--fp")
    elif product == "q5":
        cmd.append("--q5")

    if os.path.exists(cleanup_script):
        # Delegate to cleanup.sh (source of truth for cleanup operations)
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


def main():
    # 1. Handle Administrative Flags
    if len(sys.argv) > 1:
        args = [a.lower().strip() for a in sys.argv[1:]]

        # --help
        if "--help" in args or "-h" in args:
            print(f"Zest CLI v{VERSION}")
            print("")
            print("Usage: zest \"your query\"")
            print("")
            print("Model Management:")
            print("  --model --fp    Switch to FP16 model")
            print("  --model --q5    Switch to Q5 model")
            print("")
            print("Account Management:")
            print("  --logout           Log out current device (keeps model files)")
            print("  --logout --fp      Log out from FP16 only")
            print("  --logout --q5      Log out from Q5 only")
            print("  --logout --remote  Log out ANY device remotely (requires OTP)")
            print("")
            print("  --uninstall     Full uninstall (deletes model + license + app)")
            print("  --uninstall --fp   Uninstall FP16 only")
            print("  --uninstall --q5   Uninstall Q5 only")
            print("")
            print("Updates:")
            print("  --update        Check for and download updates")
            print("  --update --fp   Check for FP16 updates")
            print("  --update --q5   Check for Q5 updates")
            print("")
            print("Info:")
            print("  --status        Show current model and license status")
            print("  --version       Show version")
            sys.exit(0)

        # --version
        if "--version" in args or "-v" in args:
            print(f"Zest CLI v{VERSION}")
            sys.exit(0)

        # --update (force update check)
        if "--update" in args:
            product = None
            if "--fp" in args or "--fp16" in args:
                product = "fp16"
            elif "--q5" in args:
                product = "q5"
            else:
                product = get_active_product()

            # Clear last check time to force check
            config = load_config()
            config["last_update_check"] = 0
            save_config(config)

            print(f"🍋 Checking for updates ({PRODUCTS[product]['name']})...")
            check_for_updates(product)
            print("✅ Update check complete.")
            sys.exit(0)

        # --status
        if "--status" in args:
            config = load_config()
            active = get_active_product()
            print(f"🍋 Zest Status (CLI v{VERSION})")
            if active:
                print(f"   Active model: {PRODUCTS[active]['name']}")
            else:
                print(f"   Active model: None (no models installed)")
            print("")
            for p, info in PRODUCTS.items():
                installed = "✅" if os.path.exists(info["path"]) else "❌"
                license_key = f"{p}_license"
                trial_key = f"{p}_trial"
                trial_data = config.get(trial_key)
                license_data = config.get(license_key)
                model_ver = get_model_version(p)

                if license_data:
                    license_status = "✅ Licensed"
                elif trial_data and trial_data.get("is_trial"):
                    expires_at_str = trial_data.get("trial_expires_at")
                    try:
                        expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                        now = datetime.now(timezone.utc)
                        remaining = expires_at - now
                        days = int(remaining.total_seconds() / 86400)
                        hours = int((remaining.total_seconds() % 86400) / 3600)
                        if remaining.total_seconds() > 0:
                            license_status = f"🕐 Trial ({days}d {hours}h left)"
                        else:
                            license_status = "❌ Trial Expired"
                    except (ValueError, TypeError):
                        license_status = "🕐 Trial"
                else:
                    license_status = "❌ Not licensed"

                print(f"   {info['name']}:")
                print(f"      Installed: {installed} | {license_status} | Model v{model_ver}")

                if trial_data and trial_data.get("is_trial"):
                    email = trial_data.get("email", "")
                    print(f"      Email: {email}")

            print("")
            print("   Purchase: https://zestcli.com")
            print("   Run 'zest --update' to check for updates.")
            sys.exit(0)

        # --model --fp or --model --q5
        if "--model" in args:
            if "--fp" in args or "--fp16" in args:
                handle_model_switch("fp16")
            elif "--q5" in args:
                handle_model_switch("q5")
            else:
                print("❌ Specify model: --model --fp or --model --q5")
            sys.exit(0)

        # --logout (keeps model files)
        if "--logout" in args:
            product = None
            remote = "--remote" in args
            if "--fp" in args or "--fp16" in args:
                product = "fp16"
            elif "--q5" in args:
                product = "q5"
            handle_logout(product, remote=remote)
            sys.exit(0)

        # --uninstall (removes model files too)
        if "--uninstall" in args:
            product = None
            if "--fp" in args or "--fp16" in args:
                product = "fp16"
            elif "--q5" in args:
                product = "q5"
            handle_uninstall(product)
            sys.exit(0)

    # 2. Guard against empty queries (check before auth to avoid unnecessary auth)
    if len(sys.argv) < 2:
        print("Usage: zest \"your query here\"")
        print("       zest --help for more options")
        sys.exit(0)

    query = " ".join(sys.argv[1:])

    # 2.5. Determine active product first (needed for orphan check)
    active_product = get_active_product()

    # Check if no models are installed
    if active_product is None:
        print("❌ No Zest models are installed.")
        print("")
        print("To install Zest:")
        print("  1. Download Zest-FP16.dmg or Zest-Q5.dmg")
        print("  2. Drag the app to Applications")
        print("  3. Run 'zest' from Terminal")
        print("")
        print("Visit https://zestcli.com for more information")
        sys.exit(1)

    # 2.6. Check for orphaned installations (app deleted but files remain)
    # Only checks the active product, and only if user had a previous license
    if check_for_orphaned_installation(active_product):
        sys.exit(0)

    # 3. Query quality checks
    is_good_query, word_count, has_vague, likely_mangled = check_query_quality(query)

    if likely_mangled:
        print("⚠️  Your query looks unusually long. This often happens when")
        print("   backticks are interpreted by the shell as commands.")
        print("   Avoid using backticks in your query—use plain text instead.")
        print("   Example: zest \"unzip file.zip without using unzip\"")
        sys.exit(1)

    if not is_good_query:
        print("💡 Tip: Your query might not get the best results.\n")

        if word_count > 20:
            print(f"   Your query has {word_count} words. Try keeping it under 20 words.\n")

        if has_vague:
            print("   Try removing emotional or uncertain language and being more direct.\n")

        print("   Examples of good queries:")
        print("   ✅ 'show Node.js version'")
        print("   ✅ 'find all .jpg files in Downloads'")
        print("   ✅ 'what processes are using the most memory'\n")

        if not prompt_yes_no("🍋 Continue anyway? [y/n]: "):
            print("❌ Aborted. Try rephrasing your query!")
            sys.exit(0)
        print()

    # 4. Authenticate (active_product already determined in step 2.5)
    # Check for active trial first - if trial is active, skip full authentication
    if not check_trial_license(active_product):
        authenticate(active_product)

    # 4.5. Check for updates (silent, non-blocking)
    check_for_updates(active_product)

    # 5. Load model
    llm = load_model(active_product)

    # 6. Core AI Logic with retry loop
    failed_history: list[tuple[str, str]] = []
    user_context: str | None = None
    rejections_since_context = 0
    temp_increment = 0

    while True:
        print(f"\033[K🌶\033[0m Thinking...", end="\r", flush=True)
        command = generate_command(
            llm,
            query,
            history=failed_history,
            base_temp=0.2,
            temp_increment=temp_increment,
            user_context=user_context
        )

        print("\033[K", end="\r")
        print(f"🍋 Suggested Command:\n   \033[1;32m{command}\033[0m")

        is_expensive, reason = is_expensive_command(command)
        if is_expensive:
            print(f"\n⚠️  Warning: This command is {reason}.")
            print("   It might take a while or produce a lot of results.")
            if not prompt_yes_no("🍋 Continue? [y/n]: "):
                rejections_since_context += 1
                failed_history.append((command, "User rejected expensive command"))
                temp_increment += 1

                if rejections_since_context >= 2 and rejections_since_context % 2 == 0:
                    new_context, was_provided = prompt_for_context(user_context)
                    if was_provided:
                        user_context = new_context
                        rejections_since_context = 0
                        print(f"✅ Got it! I'll try again with that context.\n")
                        continue

                if prompt_yes_no("🍋 Try a different command? [y/n]: "):
                    continue
                else:
                    print("❌ Aborted.")
                    break
            print("-" * 30)
        else:
            try:
                if prompt_yes_no("\n\033[?25h🍋 Execute? [y/n]: "):
                    print("-" * 30)
                else:
                    rejections_since_context += 1
                    failed_history.append((command, "User rejected command"))
                    temp_increment += 1

                    if rejections_since_context >= 2 and rejections_since_context % 2 == 0:
                        new_context, was_provided = prompt_for_context(user_context)
                        if was_provided:
                            user_context = new_context
                            rejections_since_context = 0
                            print(f"✅ Got it! I'll try again with that context.\n")
                            continue

                    if prompt_yes_no("🍋 Try a different command? [y/n]: "):
                        continue
                    else:
                        print("❌ Aborted.")
                        break
            except KeyboardInterrupt:
                print("\033[?25h\n❌ Aborted.")
                break

        try:
            proc = subprocess.run(command, shell=True, capture_output=True, text=True)

            if proc.returncode != 0:
                # Command actually failed
                err_msg = proc.stderr.strip()

                if not err_msg:
                    if "mdfind" in command and len(command.split()) == 1:
                        err_msg = "mdfind requires search criteria. Command is incomplete."
                    elif "grep" in command and "no such file" in proc.stderr.lower():
                        err_msg = "File not found. Check the file path."
                    else:
                        err_msg = f"Command failed with exit code {proc.returncode}. May need different syntax or arguments."

                print(f"\n💡 Note: {err_msg}\n")
                failed_history.append((command, err_msg))
                temp_increment += 1

                if prompt_yes_no("🍋 Try again? [y/n]: "):
                    continue
                else:
                    print("\n💡 Try rephrasing your query or check if the command exists on your system.")
                    break
            else:
                # Command succeeded (return code 0)
                if proc.stdout.strip():
                    print(proc.stdout)
                else:
                    print("✅ Command executed successfully.")
                if proc.stderr.strip():
                    # Some commands write info to stderr even on success
                    print(f"   {proc.stderr.strip()}")
                break
        except KeyboardInterrupt:
            print("\033[?25h\n❌ Aborted.")
            break

    print("\033[?25h", end="")

if __name__ == "__main__":
    main()