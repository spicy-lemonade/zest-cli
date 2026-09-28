#!/usr/bin/env python3
"""
Zest CLI - Natural language to CLI command translator.

Safety
------
- Empty queries are rejected at startup to prevent invalid command generation.
- Dangerous commands (rm -rf, dd, format, etc.) trigger explicit confirmation prompts.

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
import warnings
from datetime import datetime, timezone

# Suppress charset_normalizer warning from requests in PyInstaller bundle
warnings.filterwarnings("ignore", message="Unable to find acceptable character detection dependency")

from config import VERSION, load_config, save_config
from model import (
    is_installed,
    check_for_orphaned_installation,
    check_for_updates,
    ensure_model_downloaded,
    get_model_version,
    load_model
)
from commands import (
    check_query_quality,
    is_expensive_command,
    is_dangerous_command,
    generate_command,
    prompt_yes_no,
    prompt_for_context,
    prompt_dangerous_confirmation
)
from auth import authenticate
from trial import check_trial_license
from activation import handle_logout, handle_uninstall


def _print_help():
    """Print help information."""
    print(f"Zest CLI v{VERSION}")
    print("")
    print("Usage: zest \"your query\"")
    print("")
    print("Account Management:")
    print("  --logout               Log out current device (keeps model files)")
    print("  --logout --remote      Log out ANY device remotely (requires OTP)")
    print("")
    print("  --uninstall            Full uninstall (deletes model + license + app)")
    print("")
    print("Updates:")
    print("  --update               Check for and download updates")
    print("")
    print("Info:")
    print("  --status        Show current model and license status")
    print("  --version       Show version")


def _print_status():
    """Print current status information."""
    config = load_config()
    installed = "✅" if is_installed() else "❌"
    license_data = config.get("license")
    trial_data = config.get("trial")
    model_ver = get_model_version()

    license_status = _get_license_status(license_data, trial_data)

    print(f"🍋 Zest Status (CLI v{VERSION})")
    print(f"   Installed: {installed} | {license_status} | Model v{model_ver}")

    if trial_data and trial_data.get("is_trial"):
        email = trial_data.get("email", "")
        print(f"   Email: {email}")

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
        config = load_config()
        config["last_update_check"] = 0
        save_config(config)
        print(f"🍋 Checking for updates...")
        check_for_updates()
        print("✅ Update check complete.")
        return True

    if "--status" in args:
        _print_status()
        return True

    if "--logout" in args:
        remote = "--remote" in args
        handle_logout(remote=remote)
        return True

    if "--uninstall" in args:
        handle_uninstall()
        return True

    # Suggest correct command if user forgets the dashes
    if args and args[0] == "logout" and "--logout" not in args:
        remaining_args = set(args[1:])
        if remaining_args.issubset({"--remote"}):
            print("💡 Did you mean 'zest --logout'?")
            print("   Run 'zest --help' for usage information.")
            return True

    if args and args[0] == "uninstall" and "--uninstall" not in args:
        print("💡 Did you mean 'zest --uninstall'?")
        print("   Run 'zest --help' for usage information.")
        return True

    return False


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
        print(f"\033[2K\r🌶️ Thinking...", end="", flush=True)
        command = generate_command(
            llm,
            query,
            history=failed_history,
            base_temp=0.2,
            temp_increment=temp_increment,
            user_context=user_context
        )

        print("\033[2K\r", end="")
        print(f"🍋 Suggested Command:\n   \033[1;32m{command}\033[0m")

        # Check for dangerous commands first
        is_dangerous, danger_reason = is_dangerous_command(command)
        is_expensive, expensive_reason = is_expensive_command(command)

        if is_dangerous:
            print(f"\n🚨 DANGER: This command {danger_reason}.")
            print("   This operation could have serious side effects!")
            try:
                if not prompt_dangerous_confirmation():
                    rejections_since_context, user_context, temp_increment, context_provided = _handle_rejection(
                        command, "User rejected dangerous command", failed_history,
                        rejections_since_context, user_context, temp_increment
                    )
                    if context_provided:
                        continue
                    if not _should_continue_after_rejection():
                        break
                    continue
                print("-" * 30)
            except KeyboardInterrupt:
                print("\033[?25h\n❌ Aborted.")
                break
        # Check for expensive commands
        elif is_expensive:
            print(f"\n⚠️  Warning: This command is {expensive_reason}.")
            print("   It might take a while or produce a lot of results.")
            try:
                if not prompt_yes_no("🍋 Continue? [y/n]: "):
                    rejections_since_context, user_context, temp_increment, context_provided = _handle_rejection(
                        command, "User rejected expensive command", failed_history,
                        rejections_since_context, user_context, temp_increment
                    )
                    if context_provided:
                        continue
                    if not _should_continue_after_rejection():
                        break
                    continue
                print("-" * 30)
            except KeyboardInterrupt:
                print("\033[?25h\n❌ Aborted.")
                break
        # Regular commands
        else:
            try:
                if prompt_yes_no("\n\033[?25h🍋 Execute? [y/n]: "):
                    print("-" * 30)
                else:
                    rejections_since_context, user_context, temp_increment, context_provided = _handle_rejection(
                        command, "User rejected command", failed_history,
                        rejections_since_context, user_context, temp_increment
                    )
                    if context_provided:
                        continue
                    if not _should_continue_after_rejection():
                        break
                    continue
            except KeyboardInterrupt:
                print("\033[?25h\n❌ Aborted.")
                break

        # Execute command
        should_continue, rejections_since_context, user_context, temp_increment = _execute_command(
            command, failed_history, rejections_since_context, user_context, temp_increment
        )
        if not should_continue:
            break

    print("\033[?25h", end="")


def _handle_rejection(command: str, reason: str, failed_history: list,
                      rejections_since_context: int, user_context: str | None,
                      temp_increment: int) -> tuple[int, str | None, int, bool]:
    """Handle command rejection. Returns (rejections, context, temp_increment, context_provided)."""
    rejections_since_context += 1
    failed_history.append((command, reason))
    temp_increment += 1
    context_provided = False

    if rejections_since_context >= 2 and rejections_since_context % 2 == 0:
        new_context, was_provided = prompt_for_context(user_context)
        if was_provided:
            user_context = new_context
            rejections_since_context = 0
            context_provided = True
            print(f"✅ Got it! Generating a new command with that context...\n")

    return rejections_since_context, user_context, temp_increment, context_provided


def _should_continue_after_rejection() -> bool:
    """Ask user if they want to try a different command."""
    if prompt_yes_no("🍋 Try a different command? [y/n]: "):
        return True
    else:
        print("❌ Aborted.")
        return False


def _execute_command(
    command: str,
    failed_history: list,
    rejections_since_context: int,
    user_context: str | None,
    temp_increment: int
) -> tuple[bool, int, str | None, int]:
    """Execute the command and handle results.

    Returns (should_continue, rejections_since_context, user_context, temp_increment).
    """
    try:
        proc = subprocess.run(command, shell=True, capture_output=True, text=True)

        if proc.returncode != 0:
            err_msg = _get_error_message(proc, command)
            print(f"\n💡 Note: {err_msg}\n")

            rejections_since_context, user_context, temp_increment, context_provided = _handle_rejection(
                command, err_msg, failed_history,
                rejections_since_context, user_context, temp_increment
            )

            if context_provided:
                return True, rejections_since_context, user_context, temp_increment

            if prompt_yes_no("🍋 Try again? [y/n]: "):
                return True, rejections_since_context, user_context, temp_increment
            else:
                print("\n💡 Try rephrasing your query or check if the command exists on your system.")
                return False, rejections_since_context, user_context, temp_increment
        else:
            if proc.stdout.strip():
                print(proc.stdout)
            else:
                print("✅ Command executed successfully.")
            if proc.stderr.strip():
                print(f"   {proc.stderr.strip()}")
            return False, rejections_since_context, user_context, temp_increment
    except KeyboardInterrupt:
        print("\033[?25h\n❌ Aborted.")
        return False, rejections_since_context, user_context, temp_increment


def _get_error_message(proc, command: str) -> str:
    """Get a descriptive error message for a failed command."""
    err_msg = proc.stderr.strip()

    if not err_msg:
        if "mdfind" in command and len(command.split()) == 1:
            return "mdfind requires search criteria. Command is incomplete."
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

    # 3. Check that Zest is installed
    if not is_installed():
        print("❌ Zest is not installed.")
        print("")
        print("To install Zest:")
        print("  1. Download Zest.dmg")
        print("  2. Drag the app to Applications")
        print("  3. Run 'zest' from Terminal")
        print("")
        print("Visit https://zestcli.com for more information")
        sys.exit(1)

    # 4. Check for orphaned installations
    if check_for_orphaned_installation():
        sys.exit(0)

    # 5. Query quality checks
    if not _check_query_quality_and_confirm(query):
        sys.exit(1)

    # 6. Authenticate
    if not check_trial_license():
        authenticate()

    # 7. Ensure model is downloaded (first-run or post-trial-expiry re-download)
    ensure_model_downloaded()

    # 8. Check for updates (silent, non-blocking)
    check_for_updates()

    # 9. Load model
    llm = load_model()

    # 10. Run command loop
    _run_command_loop(llm, query)


if __name__ == "__main__":
    main()
