import pytest
from sqlalchemy import Numeric, String, event
from sqlalchemy.orm import Session

from app import create_app
from app.extensions import db
from app.models.user import User


@event.listens_for(Session, "before_flush")
def _enforce_column_limits(session, flush_context, instances):
    """
    Reject values PostgreSQL would reject, even when the tests run on SQLite
    (which silently stores a 'GL14_CONPSS' in a 10-character column).
    """
    for obj in list(session.new) + list(session.dirty):
        table = getattr(obj, "__table__", None)
        if table is None:
            continue
        for column in table.columns:
            value = getattr(obj, column.key, None)
            if value is None:
                continue
            if isinstance(column.type, String) and column.type.length and len(str(value)) > column.type.length:
                raise ValueError(
                    f"value too long for {table.name}.{column.name} "
                    f"({len(str(value))} > {column.type.length}): {value!r}"
                )
            if isinstance(column.type, Numeric) and column.type.precision:
                limit = 10 ** (column.type.precision - (column.type.scale or 0))
                if abs(value) >= limit:
                    raise ValueError(f"numeric overflow for {table.name}.{column.name}: {value!r}")

@pytest.fixture
def app():
    """Create and configure a new app instance for each test."""
    app = create_app('app.config.TestConfig')
    
    with app.app_context():
        db.create_all()
        yield app
        db.session.remove()
        db.drop_all()

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def db_session(app):
    """Provides a database session for each test."""
    with app.app_context():
        yield db.session

@pytest.fixture
def auth_headers(client, db_session):
    """Returns headers with a valid JWT for an authenticated admin user."""
    # Create test admin user
    user = User(
        username="testadmin",
        email="testadmin@example.com",
        full_name="Test Admin",
        is_admin=True
    )
    user.set_password("password123")
    db_session.add(user)
    db_session.commit()

    # Login to get token
    response = client.post('/api/auth/login', json={
        "username": "testadmin",
        "password": "password123"
    })
    
    token = response.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
