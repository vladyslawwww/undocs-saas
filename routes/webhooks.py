import os

import stripe
from flask import Blueprint, jsonify, request

from models import Project, db

webhooks_bp = Blueprint("webhooks", __name__)


@webhooks_bp.route("/hooks/stripe", methods=["POST"])
def stripe_webhook():
    payload = request.get_data(as_text=True)
    sig_header = request.headers.get("Stripe-Signature")
    endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    # --- HANDLE EVENTS ---

    # 1. Subscription Created / Checkout Completed
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]

        # Use attribute access instead of .get()
        project_id = getattr(session, "client_reference_id", None)
        stripe_sub_id = getattr(session, "subscription", None)
        stripe_customer_id = getattr(session, "customer", None)

        if project_id:
            project = db.session.get(Project, int(project_id))
            if project:
                print(f"💰 WEBHOOK: Activating Project {project.id}")
                project.subscription_status = "active"
                project.stripe_subscription_id = stripe_sub_id
                project.stripe_customer_id = stripe_customer_id
                db.session.commit()

    # 2. Payment Failed
    elif event["type"] == "invoice.payment_failed":
        subscription_id = event["data"]["object"]["subscription"]
        project = Project.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()
        if project:
            print(f"❌ WEBHOOK: Payment failed for Project {project.id}")
            project.subscription_status = "past_due"
            db.session.commit()

    # 3. Subscription Deleted (User canceled)
    elif event["type"] == "customer.subscription.deleted":
        subscription_id = event["data"]["object"]["id"]
        project = Project.query.filter_by(
            stripe_subscription_id=subscription_id
        ).first()
        if project:
            print(f"⚠️ WEBHOOK: Subscription canceled for Project {project.id}")
            project.subscription_status = "canceled"
            db.session.commit()

    return jsonify(success=True)
