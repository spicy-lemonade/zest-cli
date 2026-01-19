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

   For Zest Lite:
   sudo ln -sf "/Applications/Zest-Lite.app/Contents/MacOS/zest-launcher" /usr/local/bin/zest

   For Zest Hot:
   sudo ln -sf "/Applications/Zest-Hot.app/Contents/MacOS/zest-launcher" /usr/local/bin/zest

   For Zest Extra Spicy:
   sudo ln -sf "/Applications/Zest-Extra-Spicy.app/Contents/MacOS/zest-launcher" /usr/local/bin/zest

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
                               MODEL VERSIONS
================================================================================

Zest is available in three model versions - pick your spice level:

  Zest Lite (CPU Optimized)
  - Fast and efficient for everyday CLI tasks
  - File size: ~2.9GB DMG (3GB available space needed)
  - RAM: 8GB recommended
  - No GPU required (CPU Optimized)
  - Best for: MacBook Air, Mac Mini, or any modern Mac

  Zest Hot (Balanced Performance)
  - Enhanced accuracy for complex logic and automation
  - File size: ~5.4GB DMG (6GB available space needed)
  - RAM: 12GB+ recommended
  - Balanced power (Unified Memory optimized)
  - Best for: MacBook Pro with 12GB+ RAM

  Zest Extra Spicy (Maximum Precision)
  - Highest accuracy for multi-step scripts and complex operations
  - File size: ~11.9GB DMG (16GB available space needed)
  - RAM: 32GB+ recommended
  - High-precision (Apple Silicon optimized)
  - Best for: MacBook Pro or Mac Studio with 32GB+ RAM

Each version has its own license with 2 device slots. You can purchase
multiple tiers and switch between them.

================================================================================
                        USING MULTIPLE MODELS
================================================================================

If you've purchased multiple model tiers:

1. Install all apps to /Applications

2. Check your current status:
   zest --status

3. Switch between models:
   zest --model --lite           # Use Zest Lite model
   zest --model --hot            # Use Zest Hot model
   zest --model --extra-spicy    # Use Zest Extra Spicy model

Note: If multiple models are installed, Zest defaults to the highest tier
(Extra Spicy > Hot > Lite). You can override this with the --model flag.

================================================================================
                           DEVICE MANAGEMENT
================================================================================

Your license allows installation on up to 2 devices PER PRODUCT.

If you bought multiple tiers, you have:
- 2 device slots for Zest Lite
- 2 device slots for Zest Hot
- 2 device slots for Zest Extra Spicy

LOGOUT (keeps model files, frees device slot):

  zest --logout                  # Log out from ALL products
  zest --logout --lite           # Log out from Lite only
  zest --logout --hot            # Log out from Hot only
  zest --logout --extra-spicy    # Log out from Extra Spicy only

  Use --logout to free a device slot while keeping the model on disk.
  You can re-activate later without re-downloading.

UNINSTALL (removes everything):

  zest --uninstall               # Full uninstall of ALL products
  zest --uninstall --lite        # Uninstall Lite only
  zest --uninstall --hot         # Uninstall Hot only
  zest --uninstall --extra-spicy # Uninstall Extra Spicy only

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
  │  Product: Zest Hot (Balanced Performance)
  │  Size: 5.4 GB
  └─────────────────────────────────────────────────┘

  🍋 Download new model now? [y/n]:

  Select 'y' to download and install the new model automatically.
  The download shows progress and can be cancelled with Ctrl+C.

CLI UPDATES (manual download):
  For CLI updates, you'll see a notification with the download URL.
  Download the new DMG from https://zestcli.com to update.

MANUAL UPDATE CHECK:
  zest --update                  Check all products for updates
  zest --update --lite           Check Lite for updates
  zest --update --hot            Check Hot for updates
  zest --update --extra-spicy    Check Extra Spicy for updates

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

- macOS 12.0 (Monterey) or later for Lite and Hot
- macOS 13.0 (Ventura) or later for Extra Spicy
- Apple Silicon (M1/M2/M3/M4) or Intel Mac
- Disk space:
  - Lite: ~2.9GB DMG (3GB available space)
  - Hot: ~5.4GB DMG (6GB available space)
  - Extra Spicy: ~11.9GB DMG (16GB available space)
- RAM:
  - Lite: 8GB recommended
  - Hot: 12GB recommended
  - Extra Spicy: 32GB+ recommended

================================================================================
                             COMMAND REFERENCE
================================================================================

USAGE:
  zest "your natural language query"

MODEL MANAGEMENT:
  zest --model --lite           Switch to Lite model
  zest --model --hot            Switch to Hot model
  zest --model --extra-spicy    Switch to Extra Spicy model

LOGOUT (keeps model files):
  zest --logout                  Log out from all products
  zest --logout --lite           Log out from Lite only
  zest --logout --hot            Log out from Hot only
  zest --logout --extra-spicy    Log out from Extra Spicy only

UNINSTALL (removes model files):
  zest --uninstall               Uninstall all products
  zest --uninstall --lite        Uninstall Lite only
  zest --uninstall --hot         Uninstall Hot only
  zest --uninstall --extra-spicy Uninstall Extra Spicy only

UPDATES:
  zest --update                  Check for and download updates
  zest --update --lite           Check for Lite updates
  zest --update --hot            Check for Hot updates
  zest --update --extra-spicy    Check for Extra Spicy updates

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
