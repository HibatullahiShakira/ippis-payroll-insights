"""Application configuration."""

import os
from datetime import timedelta

from dotenv import load_dotenv

load_dotenv()


def _database_uri(url):
    """
    Pin PostgreSQL URLs to the psycopg2 driver that requirements.txt installs.

    A bare 'postgresql://' lets SQLAlchemy pick its default driver, which changed
    to psycopg (v3) in SQLAlchemy 2.1, and 'postgres://' is not accepted at all.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg2://" + url[len(prefix):]
    return url


def _engine_options(uri):
    options = {
        "pool_pre_ping": True,
        "pool_recycle": 300,
    }
    if uri.startswith("postgresql+psycopg2"):
        # Send batched UPDATEs/DELETEs in pages instead of one round trip per row:
        # the database is reached over the internet, where each trip costs ~0.25s
        options["executemany_mode"] = "values_plus_batch"
    return options


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-change-in-production")
    
    # Use SQLite by default for local dev, unless DATABASE_URL is explicitly set (e.g., in Docker)
    base_dir = os.path.abspath(os.path.dirname(os.path.dirname(__file__)))
    default_db = f"sqlite:///{os.path.join(base_dir, 'payroll.db')}"
    SQLALCHEMY_DATABASE_URI = _database_uri(os.environ.get("DATABASE_URL") or default_db)
    
    SUPABASE_URL = os.environ.get("SUPABASE_URL")
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
    
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(SQLALCHEMY_DATABASE_URI)
    
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
    # In-memory SQLite for fast, isolated tests. Set TEST_DATABASE_URL to a throwaway
    # PostgreSQL database to run the same tests against the production database engine
    # (SQLite does not enforce column lengths, which once hid a bug that broke uploads).
    SQLALCHEMY_DATABASE_URI = _database_uri(os.environ.get("TEST_DATABASE_URL") or "sqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS = _engine_options(SQLALCHEMY_DATABASE_URI)
    # Avoid hashing overhead during tests
    BCRYPT_LOG_ROUNDS = 4
