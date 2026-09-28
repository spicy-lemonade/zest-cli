"""
Checkout and payment-related cloud functions for Zest CLI.
"""

import os
import json
import uuid
import base64
from datetime import datetime, timezone
from firebase_functions import https_fn, options
from firebase_admin import firestore
from polar_sdk import Polar
from standardwebhooks.webhooks import Webhook

from config import POLAR_PRODUCT_ID, SERVICE_ACCOUNT_EMAIL
from helpers import PAID_FIELD, DEVICES_FIELD, ORDER_FIELD


def _upsert_license(db, email: str, polar_data: dict) -> bool:
    """Create or update a paid license record in Firestore. Returns True on success."""
    license_ref = db.collection("licenses").document(email)

    existing_doc = license_ref.get()
    zest_user_id = (
        existing_doc.to_dict().get("zest_user_id", str(uuid.uuid4()))
        if existing_doc.exists
        else str(uuid.uuid4())
    )

    now = datetime.now(timezone.utc)
    update = {
        "zest_user_id": zest_user_id,
        "email": email,
        "polar_customer_id": polar_data.get("customer_id"),
        "updated_at": now.isoformat(),
        "updated_at_unix": int(now.timestamp()),
        PAID_FIELD: True,
        ORDER_FIELD: polar_data.get("id"),
    }
    if polar_data.get("user_id"):
        update["polar_user_id"] = polar_data["user_id"]

    try:
        license_ref.set(update, merge=True)
        print(f"License created/updated for {email}")
        return True
    except Exception as e:
        print(f"Failed to create license for {email}: {str(e)}")
        return False


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN"],
    cors=options.CorsOptions(
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def create_checkout(req: https_fn.Request) -> https_fn.Response:
    """
    Create a Polar.sh checkout session.
    Returns: {"checkout_url": "https://..."}
    """
    polar_access_token = os.environ.get("POLAR_ACCESS_TOKEN")
    polar_success_url = os.environ.get("POLAR_SUCCESS_URL")

    if not polar_access_token:
        return https_fn.Response(
            json.dumps({"error": "Missing Polar access token configuration"}),
            status=500,
            content_type="application/json"
        )

    product_id = POLAR_PRODUCT_ID
    success_url = polar_success_url or "https://zestcli.com?checkout=success"

    try:
        with Polar(
            access_token=polar_access_token,
        ) as polar:
            checkout_params = {
                "products": [product_id],
                "success_url": success_url,
            }

            print(f"Creating checkout with params: {checkout_params}")
            result = polar.checkouts.create(request=checkout_params)
            print(f"Checkout created successfully: {result.url}")

            return https_fn.Response(
                json.dumps({"checkout_url": result.url}),
                status=200,
                content_type="application/json"
            )
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"Checkout error: {error_details}")
        return https_fn.Response(
            json.dumps({"error": "Failed to create checkout. Please try again later."}),
            status=500,
            content_type="application/json"
        )


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN", "POLAR_WEBHOOK_SECRET"],
    cors=options.CorsOptions(
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def polar_webhook(req: https_fn.Request) -> https_fn.Response:
    """
    Handle Polar.sh webhook events.
    When a purchase is complete, it creates/updates a user license in Firestore.

    Note: POLAR_SUCCESS_URL is configured in the Polar dashboard, not needed here.
    """
    webhook_secret = os.environ.get("POLAR_WEBHOOK_SECRET")
    if not webhook_secret:
        print("Missing webhook secret")
        return https_fn.Response("Missing webhook secret", status=500)

    payload = req.get_data(as_text=True)

    webhook_id = req.headers.get("webhook-id")
    webhook_timestamp = req.headers.get("webhook-timestamp")
    webhook_signature = req.headers.get("webhook-signature")

    if not all([webhook_id, webhook_timestamp, webhook_signature]):
        print(f"Missing headers: id={webhook_id}, ts={webhook_timestamp}, sig={webhook_signature}")
        return https_fn.Response("Missing webhook headers", status=400)

    try:
        if webhook_secret.startswith("whsec_"):
            secret_for_verification = webhook_secret
        else:
            secret_for_verification = f"whsec_{webhook_secret}"

        wh = Webhook(secret_for_verification)
        wh.verify(payload, {
            "webhook-id": webhook_id,
            "webhook-timestamp": webhook_timestamp,
            "webhook-signature": webhook_signature,
        })
        print("Webhook signature verified successfully")
    except Exception as e:
        try:
            encoded_secret = base64.b64encode(webhook_secret.encode()).decode()
            secret_for_verification = f"whsec_{encoded_secret}"
            print(f"Retrying with base64 encoded secret, length={len(encoded_secret)}")
            wh = Webhook(secret_for_verification)
            wh.verify(payload, {
                "webhook-id": webhook_id,
                "webhook-timestamp": webhook_timestamp,
                "webhook-signature": webhook_signature,
            })
            print("Webhook signature verified successfully (with base64 encoding)")
        except Exception as e2:
            print(f"Webhook signature verification failed: {str(e)} | Retry: {str(e2)}")
            return https_fn.Response("Invalid signature", status=400)

    try:
        event = json.loads(payload)
    except json.JSONDecodeError:
        return https_fn.Response("Invalid JSON payload", status=400)

    event_type = event.get("type")
    print(f"Received webhook event: {event_type}")
    print(f"Event data keys: {list(event.get('data', {}).keys())}")

    if event_type == "order.paid":
        order = event.get("data", {})
        customer = order.get("customer", {})
        customer_email = customer.get("email")

        print(f"Customer email: {customer_email}")
        if not customer_email:
            print("No customer email found in order data")
            return https_fn.Response("No customer email in order", status=400)

        print(f"Creating/updating license for {customer_email}")
        db = firestore.client()
        polar_data = {
            "id": order.get("id"),
            "customer_id": order.get("customer_id"),
            "user_id": order.get("user_id"),
        }
        if not _upsert_license(db, customer_email, polar_data):
            return https_fn.Response("Failed to create license", status=500)

        return https_fn.Response(
            f"License updated for {customer_email}",
            status=200
        )

    if event_type == "checkout.updated":
        checkout = event.get("data", {})
        if checkout.get("status") != "succeeded":
            return https_fn.Response(f"Checkout status={checkout.get('status')}, skipping", status=200)

        customer_email = checkout.get("customer_email")
        if not customer_email:
            print("No customer email found in checkout.updated data")
            return https_fn.Response("No customer email in checkout", status=400)

        print(f"Creating/updating license via checkout.updated for {customer_email}")
        db = firestore.client()
        polar_data = {
            "id": checkout.get("id"),
            "customer_id": checkout.get("customer_id"),
        }
        if not _upsert_license(db, customer_email, polar_data):
            return https_fn.Response("Failed to create license", status=500)

        return https_fn.Response(
            f"License updated via checkout for {customer_email}",
            status=200
        )

    if event_type == "order.created":
        order = event.get("data", {})
        billing_reason = order.get("billing_reason", "")
        amount = order.get("amount", -1)
        status = order.get("status", "")

        # Only process free orders (100% discount). Paid orders are handled by order.paid.
        is_free_order = amount == 0 or status in ("confirmed", "paid")
        if not is_free_order:
            print(f"order.created: amount={amount}, status={status} — skipping, not a free order")
            return https_fn.Response("Not a free order, skipping", status=200)

        customer = order.get("customer", {})
        customer_email = customer.get("email")

        print(f"Free order.created for: {customer_email}, billing_reason={billing_reason}")
        if not customer_email:
            print("No customer email found in order.created data")
            return https_fn.Response("No customer email in order", status=400)

        db = firestore.client()
        polar_data = {
            "id": order.get("id"),
            "customer_id": order.get("customer_id"),
            "user_id": order.get("user_id"),
        }
        if not _upsert_license(db, customer_email, polar_data):
            return https_fn.Response("Failed to create license", status=500)

        return https_fn.Response(
            f"License created via free order for {customer_email}",
            status=200
        )

    if event_type == "order.refunded":
        order = event.get("data", {})
        customer = order.get("customer", {})
        customer_email = customer.get("email")

        print(f"Refund received for: {customer_email}")
        if not customer_email:
            print("No customer email found in order.refunded data")
            return https_fn.Response("No customer email in refund", status=400)

        db = firestore.client()
        license_ref = db.collection("licenses").document(customer_email)

        now = datetime.now(timezone.utc)
        try:
            license_ref.set({
                PAID_FIELD: False,
                DEVICES_FIELD: [],
                "refunded_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "updated_at_unix": int(now.timestamp()),
            }, merge=True)
            print(f"License revoked for {customer_email}")
        except Exception as e:
            print(f"Failed to revoke license for {customer_email}: {str(e)}")
            return https_fn.Response("Failed to revoke license. Please try again later.", status=500)

        return https_fn.Response(
            f"License revoked for {customer_email}",
            status=200
        )

    return https_fn.Response(f"Unhandled event: {event.get('type')}", status=200)


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN"],
    cors=options.CorsOptions(
        cors_origins=["https://zestcli.com"],
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def get_checkout_url(req: https_fn.Request) -> https_fn.Response:
    """
    Generate a Polar checkout URL for trial-to-paid conversion.
    Pre-fills the user's email for seamless checkout.
    Expects JSON: {"email": "user@example.com"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")

    if not email:
        return https_fn.Response("Missing email", status=400)

    polar_access_token = os.environ.get("POLAR_ACCESS_TOKEN")
    polar_success_url = os.environ.get("POLAR_SUCCESS_URL")

    if not polar_access_token:
        return https_fn.Response("Missing Polar access token configuration", status=500)

    success_url = polar_success_url or "https://zestcli.com?checkout=success"

    try:
        with Polar(
            access_token=polar_access_token,
        ) as polar:
            checkout_params = {
                "products": [POLAR_PRODUCT_ID],
                "success_url": success_url,
                "customer_email": email,
                "metadata": {"source": "trial_conversion"}
            }

            result = polar.checkouts.create(request=checkout_params)

            return https_fn.Response(
                json.dumps({"checkout_url": result.url}),
                status=200,
                content_type="application/json"
            )
    except Exception as e:
        return https_fn.Response(
            json.dumps({"error": "Failed to create checkout. Please try again later."}),
            status=500,
            content_type="application/json"
        )
