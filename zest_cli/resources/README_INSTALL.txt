================================================================================
                         ZEST CLI - INSTALLATION GUIDE
================================================================================

Thank you for purchasing Zest CLI!

================================================================================
                              QUICK START
================================================================================

1. Drag the Zest app to your Applications folder

2. IMPORTANT - First launch only:
   Right-click the app in Applications and select "Open"
   (This bypasses macOS Gatekeeper's extended scan which can take 30+ seconds)
   Click "Open" in the security dialog that appears

   If the app is blocked: Go to Apple menu -> System Settings -> Privacy and
   Security, then scroll down to the Security section and click "Open Anyway"

3. Open Terminal and run a command, for example:

   zest "show all files in Downloads"

4. On first run, you'll be prompted to:
   - Enter your purchase email
   - Enter the 6-digit verification code sent to your email

5. (Optional) Create a symlink for easier access:

   sudo ln -sf "/Applications/Zest.app/Contents/MacOS/zest-launcher" /usr/local/bin/zest

6. (Recommended) Add noglob alias to prevent shell expansion issues:

   For zsh (default on macOS), add this line to your ~/.zshrc:
   alias zest='noglob /usr/local/bin/zest'

   For bash, add this line to your ~/.bashrc:
   alias zest='noglob /usr/local/bin/zest'

   Then reload your shell:
   source ~/.zshrc    # or source ~/.bashrc

   This prevents special characters like * and ? from being expanded by the shell.

================================================================================
                              EXAMPLE USAGE
================================================================================

zest "find all python files modified in the last 7 days"
zest "show me the 10 largest files in Downloads"
zest "compress the logs folder into logs.tar.gz"
zest "what processes are using the most memory"
zest "list all running docker containers"

================================================================================
                                 THE MODEL
================================================================================

Zest CLI ships with a single model: a Qwen3.5-9B fine-tune (SFT + DPO),
quantized to Q5_K_M (~6.6GB).

- File size: ~7GB DMG (7GB available space needed)
- RAM: 16GB recommended
- No GPU required (CPU-optimized, uses GPU acceleration when available)
- Best for: Apple Silicon or Intel Mac with 16GB+ RAM

Your license allows installation on up to 2 devices.

================================================================================
                           DEVICE MANAGEMENT
================================================================================

Your license allows installation on up to 2 devices.

LOGOUT (keeps model files, frees device slot):

  zest --logout                  # Log out this device
  zest --logout --remote         # Log out any device remotely (requires OTP)

  Use --logout to free a device slot while keeping the model on disk.
  You can re-activate later without re-downloading.

UNINSTALL (removes everything):

  zest --uninstall               # Full uninstall

  Use --uninstall to completely remove the model file, license, and
  deregister the device. This frees disk space.

REINSTALLING:

If you try to install a model that's already on your device, you'll be
prompted to either continue (re-activate license) or cancel.

================================================================================
                              OFFLINE MODE
================================================================================

Zest runs entirely offline after initial activation!

- The AI model runs locally on your Mac
- License is verified every 14 days when online
- If offline during verification, Zest continues working
- No data is sent to any server except for license checks

================================================================================
                           AUTOMATIC UPDATES
================================================================================

Zest checks for updates once per day and notifies you when available.

MODEL UPDATES (downloaded automatically):
  When a new model version is available, you'll be prompted:

  ┌─────────────────────────────────────────────────┐
  │  🍋 Model Update available: v1.1.0
  │  Size: 6.6 GB
  └─────────────────────────────────────────────────┘

  🍋 Download new model now? [y/n]:

  Select 'y' to download and install the new model automatically.
  The download shows progress and can be cancelled with Ctrl+C.

CLI UPDATES (manual download):
  For CLI updates, you'll see a notification with the download URL.
  Download the new DMG from https://zestcli.com to update.

MANUAL UPDATE CHECK:
  zest --update                  Check for updates

================================================================================
                          APP REMOVAL CLEANUP
================================================================================

If you delete the Zest app from your Applications folder, the next time you
try to run 'zest' you'll be prompted to clean up:

- Remove leftover model files
- Deregister your device (freeing a device slot)

You can also choose to keep the files if you plan to reinstall.

================================================================================
                               REQUIREMENTS
================================================================================

- macOS 13.0 (Ventura) or later
- Apple Silicon (M1/M2/M3/M4) or Intel Mac
- Disk space: ~7GB DMG (7GB available space)
- RAM: 16GB recommended

================================================================================
                             COMMAND REFERENCE
================================================================================

USAGE:
  zest "your natural language query"

LOGOUT (keeps model files):
  zest --logout                  Log out this device
  zest --logout --remote         Log out any device remotely (requires OTP)

UNINSTALL (removes model files):
  zest --uninstall               Uninstall Zest

UPDATES:
  zest --update                  Check for and download updates

INFO:
  zest --status           Show current model and license status
  zest --version          Show version
  zest --help             Show help message

================================================================================
                                 SUPPORT
================================================================================

Website: https://zestcli.com
Email: info@zestcli.com

================================================================================
