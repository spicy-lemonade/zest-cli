# Zest CLI Testing Guide

Complete guide for testing the Polar.sh payment integration with Firebase dev and Resend dev environments.

## Testing Tools

- **create_test_license.py** - Script to create test licenses in Firestore dev
- **test_device_limit.py** - Script to test the 2-device limit enforcement
- **test_license_flow.sh** - Interactive test script (optional)

## Prerequisites

- ✅ Firebase dev project configured (`nl-cli-dev`)
- ✅ Functions deployed with Polar sandbox & Resend dev credentials
- ✅ Polar sandbox webhook configured

## Quick Start

### 1. Create Test License

```bash
cd zest_cli/test
python create_test_license.py your-email@example.com
```

Or manually in [Firestore console](https://console.firebase.google.com/project/nl-cli-dev/firestore):
- Collection: `licenses`
- Document: `your-email@example.com`
- Fields: `is_paid: true`, `devices: []`

### 2. Clear Local License (for fresh test)

```bash
rm -f "$HOME/Library/Application Support/Zest/license.json"
```

### 3. Run the CLI

```bash
cd zest_cli
python main.py --help
```

### 4. Complete Activation

1. Enter your email when prompted
2. Check your email for the 6-digit OTP (sent via Resend dev)
3. Enter the OTP code
4. ✅ Device registered!

## Verification Checklist

After successful activation:

- **Email received** with OTP code from `onboarding@resend.dev` (for now. We will make a Spicy Lemonade email in future)
- **Firestore updated** with device in `devices` array
  ```bash
  firebase use dev && firebase firestore:get licenses/your-email@example.com
  ```
- **Local license file created** at `~/Library/Application Support/Zest/license.json`
- **Second run works** without prompting (14-day lease)

## Test Scenarios

### Scenario 1: Second Device
```bash
# Clear local license and run CLI again
rm -f "$HOME/Library/Application Support/Zest/license.json"
python main.py --help
# Complete OTP flow → Device 2 registered
```

### Scenario 2: Device Limit (3rd device)

Use the test script to set up 2 mock devices, then verify a 3rd is rejected:

```bash
# Setup: Add 2 test devices to Firestore
python test_device_limit.py test

# This will:
# 1. Create 2 test devices in Firestore
# 2. Show instructions to test 3rd device rejection
# 3. Provide cleanup command when done
```

Or manually:
```bash
# After 2 devices are registered
rm -f "$HOME/Library/Application Support/Zest/license.json"
python main.py --help
# Expected: "Device limit reached"
```

### Scenario 3: Logout
```bash
python main.py --logout
# Verifies: Local file deleted & device removed from Firestore
```

### Scenario 4: Invalid Email
```bash
python main.py --help
# Enter: nonexistent@example.com
# Expected: "No license found for this email"
```

### Scenario 5: Invalid OTP
```bash
python main.py --help
# Enter valid email, then wrong OTP: 000000
# Expected: "Invalid OTP"
```

## Testing Polar Webhook (Optional)

To test the complete purchase-to-activation flow:

1. **Make test purchase** in Polar sandbox
2. **Check webhook logs**:
   ```bash
   firebase use dev && firebase functions:log --only polar_webhook
   ```
3. **Verify license created** in Firestore
4. **Test CLI activation** (steps above)

## Troubleshooting

| Issue | Solution |
|-------|----------|
| "No license found" | Create license in Firestore (step 1) |
| "Failed to send email" | Check `RESEND_API_KEY` secret is set |
| "Connection error" | Verify functions deployed: `firebase deploy --only functions` |
| "Invalid signature" | Check `POLAR_WEBHOOK_SECRET` matches Polar dashboard |

## Cleanup

```bash
# Remove test data
firebase use dev && firebase firestore:delete licenses/your-test-email@example.com
rm -f "$HOME/Library/Application Support/Zest/license.json"
```

## Configuration

The CLI is already configured for dev testing:
- **API**: `https://europe-west1-nl-cli-dev.cloudfunctions.net` (main.py:14)
- **Project**: `nl-cli-dev` (.firebaserc)
- **OTP Expiry**: 5 minutes
- **Device Limit**: 2 devices
- **Lease Duration**: 14 days
