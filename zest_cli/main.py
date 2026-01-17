#!/usr/bin/env python3
"""
Zest CLI - Natural language to CLI command translator.

Retry
-----------
- Failed/rejected commands are stored in `failed_history` and excluded from future suggestions.
- Temperature starts at 0.2, increases by 0.15 per rejection (capped at 0.8) to encourage variety.
- Every 2 rejections, user is prompted for additional context to clarify intent.

Execution
---------
- Success = return code 0 (not presence of stdout). Commands like `open`, `mkdir` produce no output.
- Expensive commands (find ~, grep -r /) trigger a warning before execution.

Input
-----
- Yes/no prompts require explicit responses (y/yes/yeah/ok or n/no/nah/nope).
- Queries over 20 words or with vague language trigger a quality warning.
"""

import sys
import os
import subprocess
from datetime import datetime, timezone

from config import VERSION, PRODUCTS, load_config, save_config
from model import (
    get_active_product,
    check_for_orphaned_installation,
    check_for_updates,
    get_model_version,
    load_model
)
from commands import (
    check_query_quality,
    is_expensive_command,
    generate_command,
    prompt_yes_no,
    prompt_for_context
)
from auth import authenticate
from trial import check_trial_license
from activation import handle_logout, handle_uninstall, handle_model_switch


def _print_help():
    """Print help information."""
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


def _print_status():
    """Print current status information."""
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

        license_status = _get_license_status(license_data, trial_data)

        print(f"   {info['name']}:")
        print(f"      Installed: {installed} | {license_status} | Model v{model_ver}")

        if trial_data and trial_data.get("is_trial"):
            email = trial_data.get("email", "")
            print(f"      Email: {email}")

    print("")
    print("   Purchase: https://zestcli.com")
    print("   Run 'zest --update' to check for updates.")


def _get_license_status(license_data: dict | None, trial_data: dict | None) -> str:
    """Get the license status string for display."""
    if license_data:
        return "✅ Licensed"

    if trial_data and trial_data.get("is_trial"):
        expires_at_str = trial_data.get("trial_expires_at")
        try:
            expires_at = datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
            now = datetime.now(timezone.utc)
            remaining = expires_at - now
            days = int(remaining.total_seconds() / 86400)
            hours = int((remaining.total_seconds() % 86400) / 3600)
            if remaining.total_seconds() > 0:
                return f"🕐 Trial ({days}d {hours}h left)"
            else:
                return "❌ Trial Expired"
        except (ValueError, TypeError):
            return "🕐 Trial"

    return "❌ Not licensed"


def _handle_admin_flags(args: list[str]) -> bool:
    """Handle administrative flags. Returns True if handled (should exit)."""
    if "--help" in args or "-h" in args:
        _print_help()
        return True

    if "--version" in args or "-v" in args:
        print(f"Zest CLI v{VERSION}")
        return True

    if "--update" in args:
        product = _get_product_from_args(args)
        config = load_config()
        config["last_update_check"] = 0
        save_config(config)
        print(f"🍋 Checking for updates ({PRODUCTS[product]['name']})...")
        check_for_updates(product)
        print("✅ Update check complete.")
        return True

    if "--status" in args:
        _print_status()
        return True

    if "--model" in args:
        if "--fp" in args or "--fp16" in args:
            handle_model_switch("fp16")
        elif "--q5" in args:
            handle_model_switch("q5")
        else:
            print("❌ Specify model: --model --fp or --model --q5")
        return True

    if "--logout" in args:
        product = None
        remote = "--remote" in args
        if "--fp" in args or "--fp16" in args:
            product = "fp16"
        elif "--q5" in args:
            product = "q5"
        handle_logout(product, remote=remote)
        return True

    if "--uninstall" in args:
        product = None
        if "--fp" in args or "--fp16" in args:
            product = "fp16"
        elif "--q5" in args:
            product = "q5"
        handle_uninstall(product)
        return True

    return False


def _get_product_from_args(args: list[str]) -> str:
    """Get product from args or use active product."""
    if "--fp" in args or "--fp16" in args:
        return "fp16"
    elif "--q5" in args:
        return "q5"
    else:
        return get_active_product()


def _check_query_quality_and_confirm(query: str) -> bool:
    """Check query quality and confirm with user if needed. Returns True to continue."""
    is_good_query, word_count, has_vague, likely_mangled = check_query_quality(query)

    if likely_mangled:
        print("⚠️  Your query looks unusually long. This often happens when")
        print("   backticks are interpreted by the shell as commands.")
        print("   Avoid using backticks in your query—use plain text instead.")
        print("   Example: zest \"unzip file.zip without using unzip\"")
        return False

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
            return False
        print()

    return True


def _run_command_loop(llm, query: str):
    """Run the main command generation and execution loop."""
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

        # Check for expensive commands
        is_expensive, reason = is_expensive_command(command)
        if is_expensive:
            print(f"\n⚠️  Warning: This command is {reason}.")
            print("   It might take a while or produce a lot of results.")
            if not prompt_yes_no("🍋 Continue? [y/n]: "):
                rejections_since_context, user_context, temp_increment = _handle_rejection(
                    command, "User rejected expensive command", failed_history,
                    rejections_since_context, user_context, temp_increment
                )
                if _should_continue_after_rejection():
                    continue
                else:
                    break
            print("-" * 30)
        else:
            try:
                if prompt_yes_no("\n\033[?25h🍋 Execute? [y/n]: "):
                    print("-" * 30)
                else:
                    rejections_since_context, user_context, temp_increment = _handle_rejection(
                        command, "User rejected command", failed_history,
                        rejections_since_context, user_context, temp_increment
                    )
                    if _should_continue_after_rejection():
                        continue
                    else:
                        break
            except KeyboardInterrupt:
                print("\033[?25h\n❌ Aborted.")
                break

        # Execute command
        should_continue = _execute_command(command, failed_history)
        if not should_continue:
            break

    print("\033[?25h", end="")


def _handle_rejection(command: str, reason: str, failed_history: list,
                      rejections_since_context: int, user_context: str | None,
                      temp_increment: int) -> tuple[int, str | None, int]:
    """Handle command rejection. Returns updated state."""
    rejections_since_context += 1
    failed_history.append((command, reason))
    temp_increment += 1

    if rejections_since_context >= 2 and rejections_since_context % 2 == 0:
        new_context, was_provided = prompt_for_context(user_context)
        if was_provided:
            user_context = new_context
            rejections_since_context = 0
            print(f"✅ Got it! I'll try again with that context.\n")

    return rejections_since_context, user_context, temp_increment


def _should_continue_after_rejection() -> bool:
    """Ask user if they want to try a different command."""
    if prompt_yes_no("🍋 Try a different command? [y/n]: "):
        return True
    else:
        print("❌ Aborted.")
        return False


def _execute_command(command: str, failed_history: list) -> bool:
    """Execute the command and handle results. Returns True to continue loop."""
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True)

        if proc.returncode != 0:
            err_msg = _get_error_message(proc, command)
            print(f"\n💡 Note: {err_msg}\n")
            failed_history.append((command, err_msg))

            if prompt_yes_no("🍋 Try again? [y/n]: "):
                return True
            else:
                print("\n💡 Try rephrasing your query or check if the command exists on your system.")
                return False
        else:
            if proc.stdout.strip():
                print(proc.stdout)
            else:
                print("✅ Command executed successfully.")
            if proc.stderr.strip():
                print(f"   {proc.stderr.strip()}")
            return False
    except KeyboardInterrupt:
        print("\033[?25h\n❌ Aborted.")
        return False


def _get_error_message(proc, command: str) -> str:
    """Get a descriptive error message for a failed command."""
    err_msg = proc.stderr.strip()

    if not err_msg:
        if "mdfind" in command and len(command.split()) == 1:
            return "mdfind requires search criteria. Command is incomplete."
        elif "grep" in command and "no such file" in proc.stderr.lower():
            return "File not found. Check the file path."
        else:
            return f"Command failed with exit code {proc.returncode}. May need different syntax or arguments."

    return err_msg


def main():
    """Main entry point for Zest CLI."""
    # 1. Handle Administrative Flags
    if len(sys.argv) > 1:
        args = [a.lower().strip() for a in sys.argv[1:]]
        if _handle_admin_flags(args):
            sys.exit(0)

    # 2. Guard against empty queries
    if len(sys.argv) < 2:
        print("Usage: zest \"your query here\"")
        print("       zest --help for more options")
        sys.exit(0)

    query = " ".join(sys.argv[1:])

    # 3. Determine active product
    active_product = get_active_product()

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

    # 4. Check for orphaned installations
    if check_for_orphaned_installation(active_product):
        sys.exit(0)

    # 5. Query quality checks
    if not _check_query_quality_and_confirm(query):
        sys.exit(1)

    # 6. Authenticate
    if not check_trial_license(active_product):
        authenticate(active_product)

    # 7. Check for updates (silent, non-blocking)
    check_for_updates(active_product)

    # 8. Load model
    llm = load_model(active_product)

    # 9. Run command loop
    _run_command_loop(llm, query)


if __name__ == "__main__":
    main()
