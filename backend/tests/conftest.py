import pytest
from app import create_app
from app.extensions import db
from app.models.user import User

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
