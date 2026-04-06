import os

from dotenv import load_dotenv
from flask import Flask, redirect, request, send_from_directory, url_for
from flask_login import LoginManager, current_user
from flask_mail import Mail

from models import User, db
from routes.api import api_bp
from routes.auth import auth_bp
from routes.main import main_bp
from routes.webhooks import webhooks_bp
from routes.internal import internal_bp

# Reload of .env to be sure
load_dotenv(override=True)

mail = Mail()


def safe_int(value, default):
    """Safely converts a value to int, returning default if None or empty."""
    if not value:
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
        "SQLALCHEMY_DATABASE_URI", "sqlite:///undocs.db"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # --- ROBUST EMAIL CONFIG ---
    app.config["MAIL_SERVER"] = os.getenv("MAIL_SERVER", "127.0.0.1")
    app.config["MAIL_PORT"] = safe_int(os.getenv("MAIL_PORT"), 1025)
    app.config["MAIL_USE_TLS"] = os.getenv("MAIL_USE_TLS", "False").lower() == "true"

    # Handle empty strings for Auth (treat as None)
    username = os.getenv("MAIL_USERNAME")
    password = os.getenv("MAIL_PASSWORD")
    app.config["MAIL_USERNAME"] = username if username else None
    app.config["MAIL_PASSWORD"] = password if password else None

    app.config["MAIL_DEFAULT_SENDER"] = os.getenv(
        "MAIL_DEFAULT_SENDER", "noreply@undocs.ai"
    )

    # DEBUG: Print Config to Terminal
    print("\n--- EMAIL CONFIGURATION ---")
    print(f"SERVER: {app.config['MAIL_SERVER']}")
    print(f"PORT:   {app.config['MAIL_PORT']} (Type: {type(app.config['MAIL_PORT'])})")
    print(f"TLS:    {app.config['MAIL_USE_TLS']}")
    print(f"AUTH:   {'Yes' if app.config['MAIL_USERNAME'] else 'No'}")
    print("---------------------------\n")

    os.makedirs("static/uploads", exist_ok=True)

    db.init_app(app)
    mail.init_app(app)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    # Extension injection
    app.extensions["mail"] = mail

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(api_bp)
    app.register_blueprint(webhooks_bp)
    app.register_blueprint(internal_bp)

    @app.before_request
    def enforce_onboarding():
        if not current_user.is_authenticated:
            return
        if request.endpoint and "static" in request.endpoint:
            return

        allowed_auth = [
            "auth.logout",
            "auth.verify_code",
            "auth.unconfirmed",
            "auth.resend_confirmation",
        ]

        if request.endpoint in allowed_auth:
            return

        # Enforce Email Confirmation
        if not current_user.is_confirmed:
            if request.endpoint != "auth.unconfirmed":
                return redirect(url_for("auth.unconfirmed"))
            return

    # --- FAVICON ROUTE ---
    @app.route("/favicon.ico")
    def favicon():
        return send_from_directory(
            os.path.join(app.root_path, "static"),
            "favicon.svg",
            mimetype="image/svg+xml",
        )

    with app.app_context():
        db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(debug=True, port=5000)
