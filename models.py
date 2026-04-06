from datetime import datetime

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.dialects.sqlite import JSON
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


class ProjectMembership(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), primary_key=True)
    role = db.Column(db.String(20), nullable=False)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=True)
    password_hash = db.Column(db.String(256), nullable=False)
    is_confirmed = db.Column(db.Boolean, default=False)
    confirmed_on = db.Column(db.DateTime, nullable=True)
    verification_code = db.Column(db.String(6), nullable=True)
    verification_expiry = db.Column(db.DateTime, nullable=True)
    memberships = db.relationship("ProjectMembership", backref="user", lazy=True)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def username(self):
        if self.name:
            return self.name
        return self.email.split("@")[0]


# --- Project Invites ---
class ProjectInvite(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # The role this code grants
    token = db.Column(db.String(20), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))  # Audit trail


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    api_key_hash = db.Column(db.String(256), unique=True, nullable=True)
    webhook_url = db.Column(db.String(300), nullable=True)
    subscription_status = db.Column(db.String(20), default="inactive")
    stripe_subscription_id = db.Column(db.String(100), nullable=True)
    stripe_customer_id = db.Column(db.String(100), nullable=True)
    page_limit = db.Column(db.Integer, default=1000)
    pages_used = db.Column(db.Integer, default=0)

    members = db.relationship("ProjectMembership", backref="project", lazy=True)
    schemas = db.relationship("DocSchema", backref="project", lazy=True)
    invites = db.relationship(
        "ProjectInvite", backref="project", lazy=True, cascade="all, delete-orphan"
    )

    def set_api_key(self, raw_key):
        self.api_key_hash = generate_password_hash(raw_key)

    def check_api_key(self, raw_key):
        return check_password_hash(self.api_key_hash, raw_key)


class DocSchema(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"))
    structure = db.Column(JSON, nullable=False)


class Document(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    filename = db.Column(db.String(300))  # The original name (Display only)

    # The actual unique file on disk
    storage_filename = db.Column(db.String(300), nullable=False)

    status = db.Column(db.String(20), default="QUEUED")
    extracted_data = db.Column(JSON, default={})
    schema_id = db.Column(db.Integer, db.ForeignKey("doc_schema.id"))
    upload_date = db.Column(db.DateTime, default=datetime.utcnow)
