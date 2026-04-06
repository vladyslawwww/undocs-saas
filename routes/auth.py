import os
from datetime import datetime, timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required, login_user, logout_user

from models import Project, ProjectInvite, ProjectMembership, User, db
from services.email_service import send_confirmation_email

auth_bp = Blueprint("auth", __name__)


def generate_otp():
    import secrets

    return str(secrets.randbelow(1000000)).zfill(6)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email")).first()
        if user and user.check_password(request.form.get("password")):
            login_user(user)
            return redirect(url_for("main.dashboard"))
        flash("Invalid email or password", "danger")
    return render_template("auth.html", mode="login")


@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        email = request.form.get("email")
        if User.query.filter_by(email=email).first():
            flash("Email already registered.", "warning")
            return redirect(url_for("auth.register"))

        otp = generate_otp()
        expiry = datetime.utcnow() + timedelta(minutes=15)

        new_user = User(
            email=email,
            name=request.form.get("name"),
            verification_code=otp,
            verification_expiry=expiry,
        )
        new_user.set_password(request.form.get("password"))
        db.session.add(new_user)
        db.session.commit()

        send_confirmation_email(email, otp)
        login_user(new_user)
        return redirect(url_for("auth.unconfirmed"))

    return render_template("auth.html", mode="register")


@auth_bp.route("/unconfirmed", methods=["GET", "POST"])
@login_required
def unconfirmed():
    if current_user.is_confirmed:
        return redirect(url_for("main.dashboard"))

    if request.method == "POST":
        code = request.form.get("code")
        if current_user.verification_code != code:
            flash("Incorrect code.", "danger")
            return redirect(url_for("auth.unconfirmed"))
        if current_user.verification_expiry < datetime.utcnow():
            flash("Code expired.", "warning")
            return redirect(url_for("auth.unconfirmed"))

        current_user.is_confirmed = True
        current_user.confirmed_on = datetime.utcnow()
        current_user.verification_code = None
        db.session.commit()

        flash("Account verified!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("unconfirmed.html")


@auth_bp.route("/resend")
@login_required
def resend_confirmation():
    otp = generate_otp()
    current_user.verification_code = otp
    current_user.verification_expiry = datetime.utcnow() + timedelta(minutes=15)
    db.session.commit()
    send_confirmation_email(current_user.email, otp)
    flash("New code sent.", "info")
    return redirect(url_for("auth.unconfirmed"))


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))


@auth_bp.route("/confirm/<code>")
@login_required
def verify_code(code):
    return redirect(url_for("auth.unconfirmed"))


# --- WORKSPACE LOGIC ---


@auth_bp.route("/onboarding")
@login_required
def onboarding_choice():
    """The Fork in the Road: Create vs Join"""
    # LOCK: If user already has projects - don't need onboarding
    if current_user.memberships:
        return redirect(url_for("main.dashboard"))

    return render_template("onboarding_choice.html")


@auth_bp.route("/create-workspace", methods=["GET", "POST"])
@login_required
def create_workspace():
    import stripe

    if request.method == "POST":
        project_name = request.form.get("project_name")

        if not current_user.has_used_trial:
            # --- PATH A: THE ONE-TIME FREE TRIAL ---
            new_project = Project(
                name=project_name, subscription_status="trial", page_limit=10
            )
            db.session.add(new_project)
            db.session.flush()

            # Mark trial as consumed
            current_user.has_used_trial = True

            mem = ProjectMembership(
                user_id=current_user.id, project_id=new_project.id, role="owner"
            )
            db.session.add(mem)
            db.session.commit()

            flash(f"Workspace '{project_name}' created! Trial active.", "success")
            return redirect(url_for("main.project_view", project_id=new_project.id))

        else:
            # --- PATH B: THE UNLIMITED PRO WORKSPACE ---
            # 1. Create the Project (Inactive until payment)
            new_project = Project(
                name=project_name,
                subscription_status="pending_payment",
                page_limit=1000,
            )
            db.session.add(new_project)
            db.session.flush()

            # 2. Add User as Owner
            mem = ProjectMembership(
                user_id=current_user.id, project_id=new_project.id, role="owner"
            )
            db.session.add(mem)
            db.session.commit()

            # 3. Create Stripe Session
            try:
                checkout_session = stripe.checkout.Session.create(
                    payment_method_types=["card"],
                    line_items=[
                        {
                            "price": os.getenv("STRIPE_PRO_PRICE_ID"),
                            "quantity": 1,
                        }
                    ],
                    mode="subscription",
                    client_reference_id=str(new_project.id),
                    success_url=os.getenv("BASE_URL") + "/workspace/success",
                    cancel_url=os.getenv("BASE_URL") + "/dashboard",
                )
                return redirect(checkout_session.url, code=303)
            except Exception as e:
                flash(f"Stripe Error: {str(e)}", "danger")
                return redirect(url_for("auth.create_workspace"))

    return render_template("setup_project.html")


@auth_bp.route("/workspace/success")
@login_required
def workspace_success():
    flash(
        "Payment is being processed! Your workspace will activate as soon as it's ready.",
        "info",
    )
    return redirect(url_for("main.dashboard"))


@auth_bp.route("/join-workspace", methods=["GET", "POST"])
@login_required
def join_workspace():
    if request.method == "POST":
        code = request.form.get("invite_code").strip()

        # 1. Look up the Invite
        invite = ProjectInvite.query.filter_by(token=code).first()

        if not invite:
            flash("Invalid or expired invitation code.", "danger")
            return redirect(url_for("auth.join_workspace"))

        project = invite.project

        # 2. Check if already member
        existing = ProjectMembership.query.filter_by(
            user_id=current_user.id, project_id=project.id
        ).first()
        if existing:
            flash("You are already in this workspace.", "info")
            return redirect(url_for("main.dashboard"))

        # 3. Add Member with ROLE from the invite
        mem = ProjectMembership(
            user_id=current_user.id, project_id=project.id, role=invite.role
        )
        db.session.add(mem)
        db.session.commit()

        flash(f"Joined {project.name} as {invite.role.capitalize()}!", "success")
        return redirect(url_for("main.dashboard"))

    return render_template("join_project.html")


@auth_bp.route("/project/<int:project_id>/pay")
@login_required
def retry_payment(project_id):
    import stripe

    stripe.api_key = os.getenv("STRIPE_SECRET_KEY")

    # 1. Find Project & Verify Ownership
    membership = ProjectMembership.query.filter_by(
        user_id=current_user.id, project_id=project_id, role="owner"
    ).first()

    if not membership:
        flash("You do not have permission to pay for this workspace.", "danger")
        return redirect(url_for("main.dashboard"))

    project = membership.project

    # 2. Prevent double payment
    if project.subscription_status == "active":
        flash("This workspace is already active.", "info")
        return redirect(url_for("main.dashboard"))

    # 3. Create NEW Stripe Session for Project
    try:
        price_id = os.getenv("STRIPE_PRO_PRICE_ID")

        checkout_session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[
                {
                    "price": price_id,
                    "quantity": 1,
                }
            ],
            mode="subscription",
            # We pass the EXISTING ID so the webhook updates this specific row
            client_reference_id=str(project.id),
            success_url=os.getenv("BASE_URL") + "/workspace/success",
            cancel_url=os.getenv("BASE_URL")
            + "/dashboard",  # Redirect to dash on cancel
        )
        return redirect(checkout_session.url, code=303)

    except Exception as e:
        flash(f"Stripe Error: {str(e)}", "danger")
        return redirect(url_for("main.dashboard"))
