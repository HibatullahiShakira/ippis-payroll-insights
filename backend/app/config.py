"""Application configuration."""

import os
from datetime import timedelta

class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    
    # Use SQLite by default for local dev, unless DATABASE_URL is explicitly set (e.g., in Docker)
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    default_db = f"sqlite:///{os.path.join(base_dir, 'payroll.db')}"
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", default_db)
    
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    JWT_SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "jwt-secret-change-in-production")
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=24)

    UPLOAD_FOLDER = os.environ.get("UPLOAD_FOLDER", os.path.join(os.path.dirname(__file__), "..", "uploads"))
    MAX_CONTENT_LENGTH = 50 * 1024 * 1024  # 50MB

    CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "*")
    DEFAULT_PAGE_SIZE = 25
    MAX_PAGE_SIZE = 100

class TestConfig(Config):
    """Testing configuration."""
    TESTING = True
    # In-memory database for fast, isolated tests
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    # Avoid hashing overhead during tests
    BCRYPT_LOG_ROUNDS = 4
