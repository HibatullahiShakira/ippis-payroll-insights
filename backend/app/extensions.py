"""Flask extensions initialization."""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager

db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()

def get_supabase():
    from flask import current_app
    from supabase import create_client
    url = current_app.config.get("SUPABASE_URL")
    key = current_app.config.get("SUPABASE_KEY")
    if url and key:
        return create_client(url, key)
    return None
