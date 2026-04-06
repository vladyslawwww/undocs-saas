import json
import os
import secrets

import stripe
from flask import (
    Blueprint,
    abort,
    current_app,  # noqa: F401
    flash,
    redirect,
    render_template,
    request,
    url_for,
)
from flask_login import current_user, login_required

from models import (
    DocSchema,
    Document,
    Project,
    ProjectInvite,
    ProjectMembership,
    User,
    db,
)

main_bp = Blueprint("main", __name__)

ROLE_POWER = {"owner": 4, "admin": 3, "verifier": 2, "watcher": 1}


# --- HELPER: Schema Sanitizer ---
def enforce_schema_descriptions(schema, key_name="root"):
    """
    Recursively ensures every field in the JSON schema has a 'description'.
    Returns (True, count) if modifications were made, (False, 0) otherwise.
    """
    modified = False
    mod_count = 0

    if isinstance(schema, dict):
        # 1. Check current node (if it's a typed field)
        if "type" in schema and "description" not in schema and key_name != "root":
            # Auto-generate description from the key
            readable_name = key_name.replace("_", " ").title()
            schema["description"] = f"Extract the {readable_name}"
            modified = True
            mod_count += 1

        # 2. Recurse into Objects ('properties')
        if "properties" in schema and isinstance(schema["properties"], dict):
            for k, v in schema["properties"].items():
                is_mod, count = enforce_schema_descriptions(v, k)
                if is_mod:
                    modified = True
                    mod_count += count

        # 3. Recurse into Arrays ('items')
        if "items" in schema and isinstance(schema["items"], dict):
            is_mod, count = enforce_schema_descriptions(
                schema["items"], f"{key_name}_item"
            )
            if is_mod:
                modified = True
                mod_count += count

    return modified, mod_count


def get_role(project_id):
    mem = ProjectMembership.query.filter_by(
        user_id=current_user.id, project_id=project_id
    ).first()
    return mem.role if mem else None


@main_bp.route("/")
def landing():
    if current_user.is_authenticated:
        return redirect(url_for("main.dashboard"))
    return render_template("landing.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    memberships = ProjectMembership.query.filter_by(user_id=current_user.id).all()

    # IF NO PROJECTS: Redirect to Onboarding Choice
    if not memberships:
        return redirect(url_for("auth.onboarding_choice"))

    # 2. Calculate Aggregate Stats
    total_projects = len(memberships)
    total_docs = 0
    pending_reviews = 0
    projects_data = []

    for mem in memberships:
        proj = mem.project
        doc_count = (
            Document.query.join(DocSchema)
            .filter(DocSchema.project_id == proj.id)
            .count()
        )
        review_count = (
            Document.query.join(DocSchema)
            .filter(DocSchema.project_id == proj.id, Document.status == "REVIEW_NEEDED")
            .count()
        )
        total_docs += doc_count
        pending_reviews += review_count

        # Calculate usage percentage for the UI
        # Safety check to avoid division by zero
        limit = proj.page_limit if proj.page_limit > 0 else 1
        usage_percent = min(int((proj.pages_used / limit) * 100), 100)

        projects_data.append(
            {
                "project": proj,
                "role": mem.role,
                "doc_count": doc_count,
                "review_count": review_count,
                "usage_percent": usage_percent,
            }
        )

    return render_template(
        "dashboard.html",
        projects=projects_data,
        stats={
            "total": total_docs,
            "pending": pending_reviews,
            "projs": total_projects,
        },
    )


@main_bp.route("/project/<int:project_id>")
@login_required
def project_view(project_id):
    role = get_role(project_id)
    if not role:
        abort(403)

    project = Project.query.get_or_404(project_id)

    # GATEKEEPER LOGIC
    if project.subscription_status not in ["active", "trial"]:
        flash(
            f"Workspace '{project.name}' is locked. Status: {project.subscription_status}",
            "warning",
        )
        return redirect(url_for("main.dashboard"))

    schemas = project.schemas
    docs = (
        Document.query.join(DocSchema)
        .filter(DocSchema.project_id == project_id)
        .order_by(Document.id.desc())
        .all()
    )
    members = ProjectMembership.query.filter_by(project_id=project_id).all()

    return render_template(
        "project.html",
        project=project,
        schemas=schemas,
        docs=docs,
        role=role,
        members=members,
        role_power=ROLE_POWER,
    )


# --- TEAM MANAGEMENT ROUTES ---


@main_bp.route("/project/<int:project_id>/members/add", methods=["POST"])
@login_required
def add_member(project_id):
    current_role = get_role(project_id)
    if ROLE_POWER.get(current_role, 0) < 3:  # Only Admin(3) or Owner(4)
        flash("You don't have permission to invite users.", "danger")
        return redirect(url_for("main.project_view", project_id=project_id))

    email = request.form.get("email")  # Changed input name in HTML below
    role = request.form.get("role")

    # 1. Check if user exists
    user_to_add = User.query.filter_by(email=email).first()
    if not user_to_add:
        flash(
            f"User with email '{email}' not found. Ask them to register first.",
            "warning",
        )
        return redirect(url_for("main.project_view", project_id=project_id))

    # 2. Check if already a member
    existing = ProjectMembership.query.filter_by(
        user_id=user_to_add.id, project_id=project_id
    ).first()
    if existing:
        flash(f"{user_to_add.username} is already in this team.", "info")
        return redirect(url_for("main.project_view", project_id=project_id))

    # 3. Add Member
    new_mem = ProjectMembership(
        user_id=user_to_add.id, project_id=project_id, role=role
    )
    db.session.add(new_mem)
    db.session.commit()

    flash(f"{user_to_add.username} added as {role}!", "success")
    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route("/project/<int:project_id>/members/remove/<int:user_id>")
@login_required
def remove_member(project_id, user_id):
    # 1. Get Actor's Role
    current_role = get_role(project_id)
    if ROLE_POWER.get(current_role, 0) < 3:  # Must be Admin(3) or Owner(4)
        abort(403)

    # 2. Get Target Membership
    mem = ProjectMembership.query.filter_by(
        user_id=user_id, project_id=project_id
    ).first()
    if not mem:
        flash("Member not found.", "warning")
        return redirect(url_for("main.project_view", project_id=project_id))

    # 3. Security: Prevent removing yourself
    if user_id == current_user.id:
        flash(
            "You cannot remove yourself. Please ask another Admin or the Owner.",
            "warning",
        )
        return redirect(url_for("main.project_view", project_id=project_id))

    # 4. Security: Rank Hierarchy Check
    # Rule: You cannot kick someone with equal or higher rank.
    target_rank = ROLE_POWER.get(mem.role, 0)
    my_rank = ROLE_POWER.get(current_role, 0)

    if target_rank >= my_rank:
        flash(f"Permission denied. You cannot remove a {mem.role.title()}.", "danger")
        return redirect(url_for("main.project_view", project_id=project_id))

    # 5. Execute
    username = mem.user.username
    db.session.delete(mem)
    db.session.commit()

    flash(f"{username} was removed from the workspace.", "success")
    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route("/project/<int:project_id>/schema/add", methods=["POST"])
@login_required
def add_schema(project_id):
    role = get_role(project_id)
    if ROLE_POWER.get(role, 0) < 3:
        abort(403)

    name = request.form.get("name")
    mode = request.form.get("mode")
    structure = {}

    if mode == "json":
        try:
            structure = json.loads(request.form.get("json_content"))
        except ValueError:
            flash("Invalid JSON syntax.", "danger")
            return redirect(url_for("main.project_view", project_id=project_id))
    else:
        # Visual Builder Logic
        keys = request.form.getlist("keys[]")
        types = request.form.getlist("types[]")
        descs = request.form.getlist("descs[]")

        properties = {}
        for k, t, d in zip(keys, types, descs):
            if k.strip():
                # If visual builder desc is empty, auto-fill it
                final_desc = d.strip() or f"Extract the {k.strip()}"
                properties[k.strip()] = {"type": t, "description": final_desc}

        structure = {
            "type": "object",
            "properties": properties,
            "required": list(
                properties.keys()
            ),  # Strict mode: require all top-level fields
        }

    # --- ENFORCE DESCRIPTIONS ---
    was_modified, count = enforce_schema_descriptions(structure)
    if was_modified:
        flash(
            f"Auto-added descriptions to {count} fields. AI performs best with detailed descriptions.",
            "warning",
        )

    new_schema = DocSchema(name=name, project_id=project_id, structure=structure)
    db.session.add(new_schema)
    db.session.commit()

    flash(f"Schema '{name}' created.", "success")
    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route("/project/<int:project_id>/settings", methods=["POST"])
@login_required
def update_settings(project_id):
    role = get_role(project_id)
    if ROLE_POWER[role] < 3:
        abort(403)

    project = Project.query.get(project_id)
    project.webhook_url = request.form.get("webhook_url")
    db.session.commit()
    flash("Settings updated", "success")
    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route("/doc/<int:doc_id>/verify", methods=["GET", "POST"])
@login_required
def verify_doc(doc_id):
    from services.ai_service import trigger_webhook

    doc = Document.query.get_or_404(doc_id)
    schema = DocSchema.query.get(doc.schema_id)
    role = get_role(schema.project_id)

    if ROLE_POWER.get(role, 0) < 2:
        abort(403)

    # --- HELPER: Parse Schema Structure for UI ---
    structure = schema.structure
    complex_mode = False
    ui_fields = []

    if isinstance(structure, dict):
        # JSON Schema Format
        # 1. Detect Complexity
        if structure.get("type") == "array":
            complex_mode = True
        else:
            props = structure.get("properties", {})
            for key, val in props.items():
                if val.get("type") in ["array", "object"]:
                    complex_mode = True

                # Prepare flat list for Simple Mode UI
                ui_fields.append(
                    {
                        "key": key,
                        "type": val.get("type", "string"),
                        "desc": val.get("description", key),
                    }
                )
    elif isinstance(structure, list):
        # List Format
        ui_fields = structure
        # Check fields for complexity (just in case)
        for item in structure:
            if item.get("type") in ["array", "object"]:
                complex_mode = True

    # --- HANDLE SUBMISSION ---
    if request.method == "POST":
        verification_mode = request.form.get("verification_mode")

        try:
            if verification_mode == "json_editor":
                # 1. Handle Raw JSON Submission
                raw_json = request.form.get("json_output")
                doc.extracted_data = json.loads(raw_json)

            else:
                # 2. Handle Standard Form Submission
                updated_data = {}
                for item in ui_fields:
                    key = item["key"]
                    # Handle Checkboxes
                    if item.get("type") == "boolean":
                        updated_data[key] = request.form.get(key) == "true"
                    else:
                        updated_data[key] = request.form.get(key)

                doc.extracted_data = updated_data

            doc.status = "COMPLETED"
            db.session.commit()
            trigger_webhook(doc)

            flash("Document Verified & Sent!", "success")
            return redirect(url_for("main.project_view", project_id=schema.project_id))

        except json.JSONDecodeError:
            flash("Error: Invalid JSON syntax. Please check your edits.", "danger")
        except Exception as e:
            flash(f"Verification failed: {str(e)}", "danger")

    return render_template(
        "verify.html",
        doc=doc,
        schema=schema,
        complex_mode=complex_mode,
        fields=ui_fields,
    )


@main_bp.route("/project/<int:project_id>/delete", methods=["POST"])
@login_required
def delete_project(project_id):
    # 1. Check Ownership
    membership = ProjectMembership.query.filter_by(
        user_id=current_user.id, project_id=project_id, role="owner"
    ).first()

    if not membership:
        abort(403)

    project = membership.project

    # 2. Cancel Stripe Subscription (if active)
    if project.stripe_subscription_id and project.subscription_status == "active":
        try:
            stripe.Subscription.delete(project.stripe_subscription_id)
            print(f"Cancelled Stripe Subscription: {project.stripe_subscription_id}")
        except Exception as e:
            # We log the error but proceed with deletion so the user isn't stuck
            print(f"Stripe Cancellation Error: {e}")
            flash(
                "Project deleted locally, but Stripe error occurred. Please contact support.",
                "warning",
            )

    try:
        # 3. Cascade Delete
        docs = (
            Document.query.join(DocSchema)
            .filter(DocSchema.project_id == project.id)
            .all()
        )
        for d in docs:
            db.session.delete(d)

        schemas = DocSchema.query.filter_by(project_id=project.id).all()
        for s in schemas:
            db.session.delete(s)

        members = ProjectMembership.query.filter_by(project_id=project.id).all()
        for m in members:
            db.session.delete(m)

        db.session.delete(project)
        db.session.commit()

        flash(f"Workspace '{project.name}' deleted and subscription cancelled.", "info")

    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting project: {str(e)}", "danger")

    return redirect(url_for("main.dashboard"))


# --- ROUTE: LEAVE PROJECT ---
@main_bp.route("/project/<int:project_id>/leave", methods=["POST"])
@login_required
def leave_project(project_id):
    # 1. Find Membership
    membership = ProjectMembership.query.filter_by(
        user_id=current_user.id, project_id=project_id
    ).first()

    if not membership:
        flash("You are not a member of this workspace.", "warning")
        return redirect(url_for("main.dashboard"))

    # 2. Prevent Owner from Leaving (Must delete instead)
    if membership.role == "owner":
        flash(
            "Owners cannot leave a workspace. You must delete it to cancel billing.",
            "danger",
        )
        return redirect(url_for("main.dashboard"))

    # 3. Leave
    project_name = membership.project.name
    db.session.delete(membership)
    db.session.commit()

    flash(f"You have left '{project_name}'.", "info")
    return redirect(url_for("main.dashboard"))


@main_bp.route("/project/<int:project_id>/invites/create", methods=["POST"])
@login_required
def create_invite(project_id):
    # 1. Check Permission (Admin+)
    role = get_role(project_id)
    if ROLE_POWER.get(role, 0) < 3:
        abort(403)

    target_role = request.form.get("role")

    # 2. Generate unique token
    token = secrets.token_urlsafe(8)

    # 3. Create Invite
    invite = ProjectInvite(
        project_id=project_id, role=target_role, token=token, created_by=current_user.id
    )
    db.session.add(invite)
    db.session.commit()

    flash(f"New invite link created for role: {target_role}", "success")
    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route("/project/<int:project_id>/invites/revoke/<int:invite_id>")
@login_required
def revoke_invite(project_id, invite_id):
    # 1. Check Permission (Admin+)
    role = get_role(project_id)
    if ROLE_POWER.get(role, 0) < 3:
        abort(403)

    invite = ProjectInvite.query.get_or_404(invite_id)

    # Security check: Ensure invite belongs to this project
    if invite.project_id != project_id:
        abort(400)

    db.session.delete(invite)
    db.session.commit()

    flash("Invite code revoked.", "info")
    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route(
    "/project/<int:project_id>/schema/<int:schema_id>/delete", methods=["POST"]
)
@login_required
def delete_schema(project_id, schema_id):
    # 1. Permission Check
    role = get_role(project_id)
    if ROLE_POWER.get(role, 0) < 3:
        abort(403)  # Admin+

    schema = DocSchema.query.get_or_404(schema_id)

    # Security: Ensure schema belongs to project
    if schema.project_id != project_id:
        abort(403)

    # 2. Cascade Delete Documents
    docs = Document.query.filter_by(schema_id=schema.id).all()
    count = len(docs)

    for d in docs:
        db.session.delete(d)

    # 3. Delete Schema
    db.session.delete(schema)
    db.session.commit()

    flash(
        f"Schema '{schema.name}' deleted (along with {count} processed documents).",
        "info",
    )
    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route(
    "/project/<int:project_id>/schema/<int:schema_id>/update", methods=["POST"]
)
@login_required
def update_schema(project_id, schema_id):
    role = get_role(project_id)
    if ROLE_POWER.get(role, 0) < 3:
        abort(403)

    schema = DocSchema.query.get_or_404(schema_id)
    if schema.project_id != project_id:
        abort(403)

    try:
        new_structure = json.loads(request.form.get("json_content"))

        # --- ENFORCE DESCRIPTIONS ---
        was_modified, count = enforce_schema_descriptions(new_structure)

        schema.structure = new_structure
        db.session.commit()

        if was_modified:
            flash(
                f"Updated schema, but auto-filled {count} missing descriptions.",
                "warning",
            )
        else:
            flash(f"Schema '{schema.name}' updated successfully.", "success")

    except ValueError:
        flash("Invalid JSON. Update failed.", "danger")

    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route("/doc/<int:doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id):
    # 1. Get Doc & Project context
    doc = Document.query.get_or_404(doc_id)
    schema = DocSchema.query.get(doc.schema_id)
    project_id = schema.project_id

    # 2. Check Permissions (Admin+ only)
    role = get_role(project_id)
    if ROLE_POWER.get(role, 0) < 3:
        abort(403)

    try:
        # 3. Delete Physical File
        upload_folder = "static/uploads"
        file_path = os.path.join(upload_folder, doc.storage_filename)

        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"File deleted: {file_path}")
        else:
            print(f"File not found on disk, skipping: {file_path}")

        # 4. Delete DB Record
        db.session.delete(doc)
        db.session.commit()

        flash("Document deleted successfully.", "success")

    except Exception as e:
        db.session.rollback()
        flash(f"Error deleting document: {str(e)}", "danger")

    return redirect(url_for("main.project_view", project_id=project_id))


@main_bp.route("/project/<int:project_id>/billing")
@login_required
def manage_billing(project_id):
    # 1. Verify Ownership
    membership = ProjectMembership.query.filter_by(
        user_id=current_user.id, project_id=project_id, role="owner"
    ).first()

    if not membership:
        flash(
            "You do not have permission to manage billing for this workspace.", "danger"
        )
        return redirect(url_for("main.dashboard"))

    project = membership.project

    # 2. Ensure they have a customer ID to manage
    if not project.stripe_customer_id:
        flash("Billing information not found for this workspace.", "warning")
        return redirect(url_for("main.project_view", project_id=project_id))

    # 3. Create a Stripe Billing Portal session
    try:
        portal_session = stripe.billing_portal.Session.create(
            customer=project.stripe_customer_id,
            return_url=url_for(
                "main.project_view", project_id=project_id, _external=True
            ),
        )
        return redirect(portal_session.url, code=303)
    except Exception as e:
        flash(f"Could not connect to billing portal: {str(e)}", "danger")
        return redirect(url_for("main.project_view", project_id=project_id))
