#!/usr/bin/env python3
"""
Test script to verify the 2-device limit is enforced.

Usage:
    python test_device_limit.py setup     # Add 2 test devices to Firestore
    python test_device_limit.py status    # Show current license state
    python test_device_limit.py cleanup   # Remove test devices
    python test_device_limit.py test      # Run the full test flow
"""
import sys
import time
from firebase_admin import initialize_app, firestore

TEST_EMAIL = "test-device-limit@example.com"
DEVICE_1 = {"uuid": "TEST-DEVICE-UUID-001", "nickname": "MacBook-Test-1"}
DEVICE_2 = {"uuid": "TEST-DEVICE-UUID-002", "nickname": "MacBook-Test-2"}


def init_firebase():
    """Initialize Firebase Admin SDK."""
    try:
        initialize_app()
    except ValueError:
        pass
    return firestore.client()


def get_license(db):
    """Get the license document from Firestore."""
    return db.collection("licenses").document(TEST_EMAIL).get()


def show_status():
    """Display the current state of the test license."""
    db = init_firebase()
    doc = get_license(db)

    print(f"\n📊 License Status: {TEST_EMAIL}")
    print("=" * 50)

    if not doc.exists:
        print("❌ No license found")
        return

    data = doc.to_dict()
    devices = data.get("devices", [])

    print(f"is_paid: {data.get('is_paid', False)}")
    print(f"devices: {len(devices)}/2")

    for i, device in enumerate(devices, 1):
        print(f"  {i}. {device.get('nickname')} ({device.get('uuid')[:20]}...)")


def setup_devices():
    """Add 2 test devices to simulate device limit being reached."""
    db = init_firebase()
    license_ref = db.collection("licenses").document(TEST_EMAIL)
    doc = license_ref.get()

    if not doc.exists:
        print(f"❌ License not found. Run: python create_test_license.py {TEST_EMAIL}")
        return False

    devices = [
        {**DEVICE_1, "registered_at": time.time()},
        {**DEVICE_2, "registered_at": time.time()},
    ]

    license_ref.update({"devices": devices})

    print(f"✅ Added 2 test devices to: {TEST_EMAIL}")
    print(f"   • {DEVICE_1['nickname']}")
    print(f"   • {DEVICE_2['nickname']}")
    return True


def cleanup():
    """Remove test devices from the license."""
    db = init_firebase()
    license_ref = db.collection("licenses").document(TEST_EMAIL)
    doc = license_ref.get()

    if not doc.exists:
        print("❌ No license found")
        return

    license_ref.update({"devices": []})
    print(f"✅ Cleared all devices from: {TEST_EMAIL}")


def run_test():
    """Run the full device limit test."""
    print("\n🧪 Device Limit Test")
    print("=" * 50)
    print("This test verifies that a 3rd device is rejected.\n")

    db = init_firebase()
    doc = get_license(db)

    if not doc.exists:
        print(f"❌ License not found. Run: python create_test_license.py {TEST_EMAIL}")
        return

    # Step 1: Setup
    print("Step 1: Setting up 2 test devices...")
    setup_devices()

    # Step 2: Show current state
    show_status()

    # Step 3: Instructions
    print("\n" + "=" * 50)
    print("Step 2: Test the 3rd device rejection")
    print("=" * 50)
    print("""
To test that a 3rd device is rejected:

1. Clear local license:
   rm -f "$HOME/Library/Application Support/Zest/license.json"

2. Run the CLI:
   cd ../
   python main.py --help

3. Enter email: test-device-limit@example.com

4. Complete OTP flow

Expected result:
   ❌ "Device limit reached" or similar error

The 3rd device should be REJECTED because 2 devices are already registered.
""")

    print("=" * 50)
    print("Step 3: Cleanup (when done testing)")
    print("=" * 50)
    print(f"\nRun: python test_device_limit.py cleanup")


def print_usage():
    """Print usage instructions."""
    print(__doc__)


def main():
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)

    command = sys.argv[1].lower()

    if command == "setup":
        setup_devices()
    elif command == "status":
        show_status()
    elif command == "cleanup":
        cleanup()
    elif command == "test":
        run_test()
    else:
        print(f"❌ Unknown command: {command}")
        print_usage()
        sys.exit(1)


if __name__ == "__main__":
    main()
