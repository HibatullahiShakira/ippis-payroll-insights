"""Flask application factory."""

import os
from flask import Flask, jsonify
from flask_cors import CORS

from .extensions import db, migrate, jwt
from .config import Config

# The fallback secrets in config.py are public (they are in the source code)
_PUBLIC_DEFAULT_SECRETS = {
    "dev-secret-key-change-in-production",
    "jwt-secret-change-in-production",
}
MIN_SECRET_LENGTH = 32


def _is_production():
    # Render sets RENDER=true on every service; APP_ENV=production covers other hosts
    return bool(os.environ.get("RENDER")) or os.environ.get("APP_ENV", "").lower() == "production"


def _check_secrets(app):
    """
    Refuse to start in production with a missing, default or short secret.

    Login tokens are signed with JWT_SECRET_KEY: anyone who knows it can create a
    token for any user, including an admin. The defaults are visible on GitHub.
    """
    problems = []
    for name in ("JWT_SECRET_KEY", "SECRET_KEY"):
        value = app.config.get(name) or ""
        if value in _PUBLIC_DEFAULT_SECRETS:
            problems.append(f"{name} is not set (the public default from the source code is being used)")
        elif len(value) < MIN_SECRET_LENGTH:
            problems.append(f"{name} is only {len(value)} characters (at least {MIN_SECRET_LENGTH} required)")
    if problems:
        raise RuntimeError(
            "Refusing to start: " + "; ".join(problems) + ". Set long random values in the service's "
            "environment variables, e.g. the output of: python -c \"import secrets; print(secrets.token_urlsafe(64))\""
        )


def create_app(config_class=Config):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config_class)
    if _is_production() and not app.config.get("TESTING"):
        _check_secrets(app)

    # Initialize extensions
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    CORS(app, resources={r"/api/*": {"origins": app.config.get("CORS_ORIGINS", "*")}})

    # Ensure upload folder exists
    os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

    # Register blueprints
    from .routes.auth import auth_bp
    from .routes.upload import upload_bp
    from .routes.employees import employees_bp
    from .routes.payslips import payslips_bp
    from .routes.analytics import analytics_bp
    from .routes.export import export_bp

    app.register_blueprint(auth_bp, url_prefix="/api/auth")
    app.register_blueprint(upload_bp, url_prefix="/api")
    app.register_blueprint(employees_bp, url_prefix="/api")
    app.register_blueprint(payslips_bp, url_prefix="/api")
    app.register_blueprint(analytics_bp, url_prefix="/api/analytics")
    app.register_blueprint(export_bp, url_prefix="/api")

    # Tables are already created, removing db.create_all() to prevent
    # Gunicorn pre-fork SSL connection errors. New columns/tables are added on the
    # first request instead (inside the worker, so no pre-fork connection).
    from .schema import ensure_schema

    @app.before_request
    def _upgrade_schema_once():
        try:
            ensure_schema()
        except Exception:
            app.logger.exception("Database schema upgrade failed")

    # Error handlers
    @app.errorhandler(404)
    def not_found(error):
        return jsonify({"error": "Resource not found"}), 404

    @app.errorhandler(413)
    def too_large(error):
        limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        return jsonify({"error": f"The upload is too large. The limit is {limit_mb}MB for both files together."}), 413

    @app.errorhandler(422)
    def unprocessable(error):
        return jsonify({"error": "Unprocessable request"}), 422

    @app.errorhandler(500)
    def internal_error(error):
        return jsonify({"error": "Internal server error"}), 500

    # Health check
    @app.route("/api/health")
    def health():
        return jsonify({"status": "healthy"})

    from .utils import admin_required

    @app.route("/api/init-db-tables", methods=["POST"])
    @admin_required
    def init_db_tables():
        """Create any missing database tables (admin only; tables are also created as needed)."""
        try:
            db.create_all()
            return jsonify({"status": "success", "message": "All missing tables were created successfully!"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    return app
