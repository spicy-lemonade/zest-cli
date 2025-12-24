import os
import stripe
from firebase_functions import https_fn, options
from firebase_admin import initialize_app, firestore

initialize_app()

# Remove "STRIPE_WEBHOOK_SECRET" when creating the initial webhook to Firebase and also modify line 23
# to use the temporary dummy value instead. Re-add these when running `firebase functions:secrets:set STRIPE_WEBHOOK_SECRET`
@https_fn.on_request(
    region="europe-west1",
    secrets=["STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"], 
    cors=options.CorsOptions(
        cors_origins="*",
        cors_methods=["POST"],
    ),
)
def stripe_webhook(req: https_fn.Request) -> https_fn.Response:
    """
    Handle Stripe webhook events for one-time purchases.
    Verifies webhook signature and updates Firestore licenses collection.
    """
    stripe.api_key = os.environ.get("STRIPE_SECRET_KEY")
    # webhook_secret = "temporary_dummy_value"
    webhook_secret = os.environ.get("STRIPE_WEBHOOK_SECRET")

    if not stripe.api_key or not webhook_secret:
        return https_fn.Response(
            "Missing required secrets",
            status=500,
        )

    payload = req.get_data(as_text=True)
    sig_header = req.headers.get("Stripe-Signature")

    if not sig_header:
        return https_fn.Response(
            "Missing Stripe signature header",
            status=400,
        )

    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
    except ValueError:
        return https_fn.Response(
            "Invalid payload",
            status=400,
        )
    except stripe.error.SignatureVerificationError:
        return https_fn.Response(
            "Invalid signature",
            status=400,
        )

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        customer_email = session.get("customer_details", {}).get("email")

        if not customer_email:
            return https_fn.Response(
                "No customer email in session",
                status=400,
            )

        db = firestore.client()
        license_ref = db.collection("licenses").document(customer_email)

        license_ref.set({
            "is_paid": True,
        }, merge=True)

        return https_fn.Response(
            f"License updated for {customer_email}",
            status=200,
        )

    return https_fn.Response(
        f"Unhandled event type: {event['type']}",
        status=200,
    )
