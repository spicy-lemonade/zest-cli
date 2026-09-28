# Zest CLI - Commercial Edition

Licensed version of Zest with 2-device activation, OTP verification, and macOS packaging.

## 📁 Structure

```
zest_cli/
├── main.py                 # Licensed CLI with activation flow
├── requirements.txt        # Python dependencies
├── scripts/build_dmg.sh    # DMG build script
├── resources/              # Cleanup script, install guide, model license
└── README.md               # This file
```

## 🚀 Quick Start

### Usage

**During Development/Testing**:
```bash
python main.py "your query here"
```

**After Installation**:
```bash
zest "your query here"
```

**IMPORTANT**: Don't include "zest" in the query when testing!

✅ Correct:
```bash
python main.py "show me all running docker containers"
# Output: docker ps
```

❌ Wrong:
```bash
python main.py zest show me all running docker containers
# This includes "zest" in the query, confusing the model
```

### Setup

1. **Configure API endpoint** in `config.py`:
   ```python
   API_BASE = "https://europe-west1-<ZEST_PROJECT_ID>.cloudfunctions.net"
   ```

2. **Deploy backend**:
   ```bash
   cd ../functions
   firebase deploy --only functions
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Test locally**:
   ```bash
   python main.py "list files"
   ```

5. **Build for distribution**:
   ```bash
   ./scripts/build_dmg.sh
   ```

## 🔐 How It Works

1. **Purchase**: User buys via Polar → Webhook creates Firestore license
2. **First Run**: CLI prompts for email → Backend sends OTP
3. **Activation**: User enters OTP → Backend registers device UUID
4. **Validation**: 14-day local lease with periodic online sync
5. **2-Device Limit**: Enforced server-side

## 🗑️ Cleanup Commands

Commands that work even after uninstalling (via standalone `main.py` fallback):

### `zest --status`
Shows installation and license status:
```bash
zest --status
```

**Example output**:
```
🍋 Zest Status (CLI v1.0.0)
   Installed: ✅ | Licensed: ✅ | Model v1.0.0
```

### `zest --logout`
Deregisters device and removes license data, but **keeps the model file** on disk. Frees up a device slot on your account.

```bash
zest --logout

# Log out any device remotely (requires OTP)
zest --logout --remote
```

**What gets removed**:
- License data from config
- Device registration on server

**What stays**:
- Model file in `~/.zest/`
- App bundle in `/Applications/`
- CLI wrapper at `/usr/local/bin/zest`

### `zest --uninstall`
Complete removal: deregisters device, removes license data, **deletes the model file**, and removes the app bundle from Applications.

```bash
zest --uninstall
```

**What gets removed**:
- License data from config
- Device registration on server
- Model file (`~/.zest/*.gguf`)
- App bundle from `/Applications/`
- Empty directories (`~/.zest/`, config dir)

**What stays**:
- CLI wrapper at `/usr/local/bin/zest` (for running cleanup commands)
- Standalone `main.py` at `~/.zest/` (if the model is gone)
- Shell alias in `~/.zshrc` or `~/.bashrc`

**To completely remove Zest**:
```bash
sudo rm /usr/local/bin/zest
rm -rf ~/.zest
rm -rf ~/Library/Application\ Support/Zest
# Manually remove alias from ~/.zshrc or ~/.bashrc
```

### Key Difference: `--logout` vs `--uninstall`

- **`--logout`**: "Free up a device slot but keep the model file locally"
- **`--uninstall`**: "Remove everything (license + model file + app)"

## 🧪 Testing

**Prerequisites**:
- Backend deployed
- `API_BASE` configured in `config.py`
- Model at `~/.zest/qwen3.5_9b_Q5_K_M.gguf`
- Dependencies installed

### Test 1: First-Time Activation

```bash
# Clear existing license
rm -f "$HOME/Library/Application Support/Zest/config.json"

# Create test license
cd ../functions
python create_test_license.py your-email@example.com
cd ../zest_cli

# Run CLI
python main.py "list files"
```

**Expected**: Email prompt → OTP sent → Device registered → Command generated

**Verify**:
```bash
cat "$HOME/Library/Application Support/Zest/config.json"
firebase firestore:get licenses/your-email@example.com
```

### Test 2: Existing License

```bash
python main.py "list files"
```

**Expected**: No OTP prompt (14-day lease still valid)

### Test 3: Logout

```bash
python main.py --logout
```

**Expected**: Device deregistered, local license deleted

## 🔧 Configuration

| Setting | Location | Default |
|---------|----------|---------|
| API Endpoint | `config.py` | `europe-west1-<ZEST_PROJECT_ID>.cloudfunctions.net` |
| Model Path | `config.py` | `~/.zest/qwen3.5_9b_Q5_K_M.gguf` |
| Lease Duration | `config.py` | 14 days |
| Device Limit | `../functions/config.py` | 2 devices |
| OTP Expiry | `../functions/config.py` | 10 minutes |

## 🐛 Troubleshooting

### Authentication Issues

**Authentication doesn't trigger**
- Valid 14-day lease cached: `cat "$HOME/Library/Application Support/Zest/config.json"`
- Clear: `rm -f "$HOME/Library/Application Support/Zest/config.json"`

**"No license found"**
- Verify Polar webhook is working
- Check Firestore: `firebase firestore:get licenses/your-email@example.com`

**Network error**
- Check `API_BASE` in `config.py`
- Verify functions deployed: `firebase deploy --only functions`
- Test endpoint: `curl https://europe-west1-<ZEST_PROJECT_ID>.cloudfunctions.net/send_otp`

### Model Issues

**Wrong command or repeats query**
- Don't include "zest" in test queries (see Usage section)
- Model exists: `ls -lh ~/.zest/*.gguf`
- Test examples:
  - `python main.py "list files"` → `ls`
  - `python main.py "show running processes"` → `ps aux`
  - `python main.py "show disk usage"` → `df -h`

**Model not found**
- Download to `~/.zest/qwen3.5_9b_Q5_K_M.gguf`

### Testing Issues

**Wrong directory**
- Run from `zest_cli/` directory, not `zest_cli/test/`

## 📦 Distribution

### Testing (Unsigned)
```bash
./scripts/build_dmg.sh
```

### Production (Signed & Notarized)
1. Get Apple Developer account ($99/year)
2. Create Developer ID certificates
3. Set `APPLE_SIGNING_IDENTITY`, `APPLE_ID`, `APPLE_TEAM_ID` before running `build_dmg.sh`
4. Notarizing and stapling happen automatically when those are set

## 📊 Firestore Schema

```
licenses/{email}
  ├─ is_paid: boolean
  ├─ devices: array[{uuid, nickname, registered_at}]
  ├─ is_trial: boolean
  ├─ trial_started_at: timestamp
  ├─ trial_expires_at: timestamp
  ├─ trial_devices: array[{uuid, nickname, registered_at}]
  ├─ polar_order_id: string
  ├─ otp_code: string (temporary)
  ├─ otp_expiry: datetime (temporary)
  └─ created_at: timestamp
```

## 📄 License

Copyright © 2026 Spicy Lemonade. All rights reserved.
