#!/usr/bin/env python3
import sys
import os
import subprocess
import contextlib
import platform
import json
import requests
import time
import multiprocessing

# --- Configuration ---
MODEL_PATH = os.path.expanduser("~/.zest/gemma3_4b_Q4_K_M.gguf")
API_BASE = "https://europe-west1-nl-cli-dev.cloudfunctions.net"
CONFIG_DIR = os.path.expanduser("~/Library/Application Support/Zest")
TOKEN_FILE = os.path.join(CONFIG_DIR, "license.json")
LEASE_DURATION = 1209600  # 14 days in seconds

def get_hw_id():
    """Captures the macOS Hardware UUID as per your spec."""
    cmd = 'ioreg -d2 -c IOPlatformExpertDevice | awk -F"\\"" \'/IOPlatformUUID/{print $(NF-1)}\''
    return subprocess.check_output(cmd, shell=True).decode().strip()

def authenticate():
    """The Gatekeeper: Checks local 14-day lease or starts OTP flow."""
    hw_id = get_hw_id()

    # 1. Check for local lease
    if os.path.exists(TOKEN_FILE):
        try:
            with open(TOKEN_FILE, "r") as f:
                creds = json.load(f)
            
            email = creds.get("email")
            last_verified = creds.get("last_verified", 0)
            current_time = time.time()

            # If the 14-day lease is still valid, bypass network entirely
            if (current_time - last_verified) < LEASE_DURATION:
                return True

            # Lease expired: Attempt silent background refresh
            print("\033[K🌶  Refreshing license...", end="\r")
            try:
                res = requests.post(f"{API_BASE}/validate_device",
                                    json={"email": email, "device_uuid": hw_id},
                                    timeout=4)
                if res.status_code == 200:
                    creds["last_verified"] = current_time
                    with open(TOKEN_FILE, "w") as f:
                        json.dump(creds, f)
                    print("\033[K", end="") # Clear refresh line
                    return True
                elif res.status_code == 403:
                    print(f"\n❌ License revoked or moved: {res.text}")
                    os.remove(TOKEN_FILE)
                    sys.exit(1)
            except requests.exceptions.RequestException:
                # Offline Grace Period: Let them in if server is unreachable
                return True
        except (json.JSONDecodeError, KeyError):
            pass

    # 2. Welcome/OTP Flow (For new devices or expired/revoked licenses)
    print("\n🍋 Welcome to Zest! Activation Required.")
    email = input("Enter your purchase email: ").strip()

    print(f"🌶  Sending code to {email}...", end="\r")
    try:
        otp_res = requests.post(f"{API_BASE}/send_otp", json={"email": email})
        if otp_res.status_code != 200:
            print(f"\n❌ Error: {otp_res.text}")
            sys.exit(1)
    except Exception as e:
        print(f"\n❌ Connection error: {e}")
        sys.exit(1)

    print("\033[K📧 Code sent!")
    code = input("Enter the 6-digit code: ").strip()

    # Get device nickname from system
    nickname = platform.node()

    # Final Verification and Device Registration
    verify_res = requests.post(f"{API_BASE}/verify_otp_and_register",
                            json={
                                "email": email,
                                "otp": code,
                                "device_uuid": hw_id,
                                "device_nickname": nickname
                            })

    if verify_res.status_code == 200:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(TOKEN_FILE, "w") as f:
            json.dump({"email": email, "last_verified": time.time()}, f)
        print("✅ Success! Device linked.")
        return True
    else:
        print(f"❌ Activation failed: {verify_res.text}")
        sys.exit(1)

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

from llama_cpp import Llama

def load_model():
    if not os.path.exists(MODEL_PATH):
        sys.stderr.write(f"❌ Error: Model not found at {MODEL_PATH}\n")
        sys.exit(1)
    
    recommended_threads = max(1, multiprocessing.cpu_count() // 2)

    with suppress_c_logs():
        try:
            model = Llama(
                model_path=MODEL_PATH,
                n_ctx=2048,
                n_gpu_layers=-1,
                n_threads=recommended_threads,
                verbose=False
            )
            return model
        except Exception:
            return Llama(
                model_path=MODEL_PATH,
                n_ctx=2048,
                n_gpu_layers=0,
                n_threads=recommended_threads,
                verbose=False
            )

def generate_command(llm, query):
    current_os = platform.system()
    os_name = "macOS" if current_os == "Darwin" else current_os
    
    system_part = (
        "<start_of_turn>system\n"
        f"You are a command line tool running on {os_name}. Output the exact command only.\n"
        "Identity: You are a small language model developed by Spicy Lemonade.\n"
        "Rules: Output the exact command ONLY. No markdown.\n"
        "<end_of_turn>\n"
    )
    
    full_prompt = f"{system_part}<start_of_turn>user\n{query}<end_of_turn>\n<start_of_turn>model\n"
    output = llm(full_prompt, max_tokens=128, stop=["<end_of_turn>", "\n"], echo=False, temperature=0.1)
    return output['choices'][0]['text'].strip()

def main():
    # 1. Handle Administrative Flags
    if len(sys.argv) > 1:
        flag = sys.argv[1].lower().strip()
        if flag == "--logout":
            if os.path.exists(TOKEN_FILE):
                os.remove(TOKEN_FILE)
                print("🍋 Logged out successfully.")
            else:
                print("🍋 You are not currently logged in.")
            sys.exit(0)
        if flag in ["--help", "-h"]:
            print("Usage: zest \"your query\"")
            print("Flags: --logout")
            sys.exit(0)

    # 2. Licensing Gatekeeper
    authenticate()

    # 3. Guard against empty queries
    if len(sys.argv) < 2:
        print("Usage: zest \"your query here\"")
        sys.exit(0)

    # 4. Core AI Logic
    query = " ".join(sys.argv[1:])
    print("\033[?25l\033[K🌶   Thinking...", end="\r")

    llm = load_model()
    command = generate_command(llm, query)

    print("\033[K", end="\r") 
    print(f"\033[K🍋 Suggested Command:\n   \033[1;32m{command}\033[0m")

    try:
        choice = input("\n\033[?25h🍋 Execute? [y/n]: ").lower().strip()
        if choice == "y":
            print("-" * 30)
            subprocess.run(command, shell=True)
        else:
            print("❌ Aborted.")
    except KeyboardInterrupt:
        print("\033[?25h\n❌ Aborted.")
    finally:
        print("\033[?25h", end="")

if __name__ == "__main__":
    main()