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

from config import POLAR_PRODUCT_IDS, SERVICE_ACCOUNT_EMAIL
from helpers import get_product_fields


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def create_checkout(req: https_fn.Request) -> https_fn.Response:
    """
    Create a Polar.sh checkout session for a product.
    Expects JSON: {"product": "lite"}, {"product": "hot"}, or {"product": "extra_spicy"}
    Returns: {"checkout_url": "https://..."}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response(
            json.dumps({"error": "Invalid JSON"}),
            status=400,
            content_type="application/json"
        )

    product = data.get("product")

    if not product:
        return https_fn.Response(
            json.dumps({"error": "Missing product field"}),
            status=400,
            content_type="application/json"
        )

    if product not in POLAR_PRODUCT_IDS:
        return https_fn.Response(
            json.dumps({"error": f"Invalid product. Available: {list(POLAR_PRODUCT_IDS.keys())}"}),
            status=400,
            content_type="application/json"
        )

    polar_access_token = os.environ.get("POLAR_ACCESS_TOKEN")
    polar_success_url = os.environ.get("POLAR_SUCCESS_URL")

    if not polar_access_token:
        return https_fn.Response(
            json.dumps({"error": "Missing Polar access token configuration"}),
            status=500,
            content_type="application/json"
        )

    product_id = POLAR_PRODUCT_IDS[product]
    success_url = polar_success_url or "https://zestcli.com?checkout=success"

    try:
        with Polar(
            access_token=polar_access_token,
            server="sandbox",
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
            json.dumps({"error": f"Failed to create checkout: {str(e)}"}),
            status=500,
            content_type="application/json"
        )


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN", "POLAR_WEBHOOK_SECRET"],
    cors=options.CorsOptions(
        cors_origins="*",
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

        print(f"Secret format: starts_with_whsec={webhook_secret.startswith('whsec_')}, length={len(webhook_secret)}")
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

        print(f"Customer data: {customer}")
        print(f"Customer email: {customer_email}")

        if not customer_email:
            print("No customer email found in order data")
            return https_fn.Response("No customer email in order", status=400)

        product = order.get("product", {})
        product_name = product.get("name", "").lower()
        product_id = order.get("product_id") or product.get("id")

        print(f"Product data: name={product.get('name')}, id={product_id}")

        if product_id == "PLACEHOLDER_LITE_PRODUCT_ID":
            product_type = "lite"
        elif product_id == "PLACEHOLDER_HOT_PRODUCT_ID":
            product_type = "hot"
        elif product_id == "PLACEHOLDER_EXTRA_SPICY_PRODUCT_ID":
            product_type = "extra_spicy"
        elif "lite" in product_name or "qwen3" in product_name or "4b" in product_name:
            product_type = "lite"
        elif "hot" in product_name or "coder" in product_name and "q5" in product_name:
            product_type = "hot"
        elif "extra" in product_name or "spicy" in product_name or "fp16" in product_name:
            product_type = "extra_spicy"
        else:
            print(f"Warning: Could not determine product type, defaulting to lite")
            product_type = "lite"

        paid_field, devices_field, order_field = get_product_fields(product_type)

        db = firestore.client()
        license_ref = db.collection("licenses").document(customer_email)

        existing_doc = license_ref.get()
        if existing_doc.exists:
            existing_data = existing_doc.to_dict()
            zest_user_id = existing_data.get("zest_user_id", str(uuid.uuid4()))
        else:
            zest_user_id = str(uuid.uuid4())

        now = datetime.now(timezone.utc)
        print(f"Creating/updating license for {customer_email}, product={product_type}")
        try:
            license_ref.set({
                "zest_user_id": zest_user_id,
                "email": customer_email,
                "polar_customer_id": order.get("customer_id"),
                "polar_user_id": order.get("user_id"),
                "updated_at": now.isoformat(),
                "updated_at_unix": int(now.timestamp()),
                paid_field: True,
                order_field: order.get("id")
            }, merge=True)
            print(f"License created successfully for {customer_email}")
        except Exception as e:
            print(f"Failed to create license: {str(e)}")
            return https_fn.Response(f"Failed to create license: {str(e)}", status=500)

        return https_fn.Response(
            f"License for {product_type} updated for {customer_email}",
            status=200
        )

    return https_fn.Response(f"Unhandled event: {event.get('type')}", status=200)


@https_fn.on_request(
    region="europe-west1",
    secrets=["POLAR_ACCESS_TOKEN"],
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
    service_account=SERVICE_ACCOUNT_EMAIL,
)
def get_checkout_url(req: https_fn.Request) -> https_fn.Response:
    """
    Generate a Polar checkout URL for trial-to-paid conversion.
    Pre-fills the user's email for seamless checkout.
    Expects JSON: {"email": "user@example.com", "product": "lite", "hot", or "extra_spicy"}
    """
    try:
        data = req.get_json()
    except Exception:
        return https_fn.Response("Invalid JSON", status=400)

    email = data.get("email")
    product = data.get("product", "lite")

    if not email:
        return https_fn.Response("Missing email", status=400)

    if product not in POLAR_PRODUCT_IDS:
        return https_fn.Response(
            f"Invalid product. Available: {list(POLAR_PRODUCT_IDS.keys())}",
            status=400
        )

    polar_access_token = os.environ.get("POLAR_ACCESS_TOKEN")
    polar_success_url = os.environ.get("POLAR_SUCCESS_URL")

    if not polar_access_token:
        return https_fn.Response("Missing Polar access token configuration", status=500)

    product_id = POLAR_PRODUCT_IDS[product]
    success_url = polar_success_url or "https://zestcli.com?checkout=success"

    try:
        with Polar(
            access_token=polar_access_token,
            server="sandbox",
        ) as polar:
            checkout_params = {
                "products": [product_id],
                "success_url": success_url,
                "customer_email": email,
                "metadata": {"source": "trial_conversion", "product": product}
            }

            result = polar.checkouts.create(request=checkout_params)

            return https_fn.Response(
                json.dumps({"checkout_url": result.url}),
                status=200,
                content_type="application/json"
            )
    except Exception as e:
        return https_fn.Response(
            json.dumps({"error": f"Failed to create checkout: {str(e)}"}),
            status=500,
            content_type="application/json"
        )
