"""Authentication routes — register, login, user info."""

from datetime import datetime, timezone
from flask import Blueprint, request, jsonify
from flask_jwt_extended import (
    create_access_token,
    jwt_required,
    get_jwt_identity,
    verify_jwt_in_request,
)

from ..extensions import db
from ..models.user import User
from ..utils import current_user_from_jwt

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/register", methods=["POST"])
def register():
    """
    Register a new accountant user.

    Open only while no users exist (first-time setup); after that an admin
    must be logged in to create accounts.
    """
    data = request.get_json(silent=True) or {}

    creator_is_admin = False
    if User.query.count() > 0:
        verify_jwt_in_request()
        creator = current_user_from_jwt()
        if not creator or not creator.is_active or not creator.is_admin:
            return jsonify({"error": "Admin access required"}), 403
        creator_is_admin = True

    # Validate required fields
    required = ["username", "email", "password", "full_name"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"'{field}' is required"}), 400

    # Check for existing user
    if User.query.filter_by(username=data["username"]).first():
        return jsonify({"error": "Username already exists"}), 409
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 409

    # Create user
    user = User(
        username=data["username"],
        email=data["email"],
        full_name=data["full_name"],
        # The very first account is the administrator; later ones only if an admin says so
        is_admin=bool(data.get("is_admin")) if creator_is_admin else True,
    )
    user.set_password(data["password"])

    db.session.add(user)
    db.session.commit()

    return jsonify({"message": "User registered successfully", "user": user.to_dict()}), 201


@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticate user and return JWT token."""
    data = request.get_json(silent=True) or {}

    if not data.get("username") or not data.get("password"):
        return jsonify({"error": "Username and password are required"}), 400

    user = User.query.filter_by(username=data["username"]).first()

    if not user or not user.check_password(data["password"]):
        return jsonify({"error": "Invalid username or password"}), 401

    if not user.is_active:
        return jsonify({"error": "Account is deactivated"}), 403

    # Update last login
    user.last_login = datetime.now(timezone.utc)
    db.session.commit()

    # Create JWT token
    access_token = create_access_token(identity=str(user.id))

    return jsonify({
        "message": "Login successful",
        "access_token": access_token,
        "user": user.to_dict(),
    })


@auth_bp.route("/me", methods=["GET"])
@jwt_required()
def get_current_user():
    """Get the currently authenticated user's info."""
    user_id = get_jwt_identity()
    user = User.query.get(int(user_id))

    if not user:
        return jsonify({"error": "User not found"}), 404

    return jsonify({"user": user.to_dict()})


@auth_bp.route("/users", methods=["GET"])
@jwt_required()
def list_users():
    """List all users (admin only)."""
    current_user_id = get_jwt_identity()
    current_user = User.query.get(int(current_user_id))

    if not current_user or not current_user.is_admin:
        return jsonify({"error": "Admin access required"}), 403

    users = User.query.all()
    return jsonify({"users": [u.to_dict() for u in users]})
