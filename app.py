import os

from dotenv import load_dotenv
from flask import Flask, redirect, request, send_from_directory, url_for
from flask_login import LoginManager, current_user
from flask_migrate import Migrate

from models import User, db
from routes.api import api_bp
from routes.auth import auth_bp
from routes.internal import internal_bp
from routes.main import main_bp
from routes.webhooks import webhooks_bp
from services.keep_alive import start_keep_alive

# Reload of .env to be sure
load_dotenv(override=True)


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
    db_url = os.getenv("DATABASE_URL", "sqlite:///undocs.db")
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = db_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    app.config["MAIL_DEFAULT_SENDER"] = os.getenv(
        "MAIL_DEFAULT_SENDER", "onboarding@resend.dev"
    )

    db.init_app(app)
    migrate = Migrate(app, db)

    login_manager = LoginManager()
    login_manager.login_view = "auth.login"
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

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

    # Start the keep-alive thread ONLY in production
    if os.getenv("ENV") == "production" or not app.debug:
        start_keep_alive()

    # with app.app_context():
    #     db.create_all()

    return app


if __name__ == "__main__":
    app = create_app()
    # Use the PORT env var if available, else default to 5000
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
