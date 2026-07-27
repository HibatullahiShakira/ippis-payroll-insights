import pytest
from app.models.user import User
from app.extensions import db

def test_password_hashing(app):
    """Test that passwords are automatically hashed when set."""
    user = User(username="test", email="test@example.com")
    user.set_password("mysecret")
    assert user.password_hash is not None
    assert user.password_hash != "mysecret"
    assert user.check_password("mysecret") is True
    assert user.check_password("wrong") is False

def test_register_route(client, db_session):
    """Test user registration endpoint."""
    response = client.post('/api/auth/register', json={
        "username": "newuser",
        "email": "newuser@example.com",
        "password": "password123",
        "full_name": "New User"
    })
    assert response.status_code == 201
    
    # Verify user was created in db
    user = User.query.filter_by(username="newuser").first()
    assert user is not None
    assert user.full_name == "New User"

def test_register_duplicate(client, db_session):
    """Test duplicate registration fails."""
    # Create first user
    user = User(username="existing", email="existing@example.com", full_name="Existing")
    user.set_password("pass")
    db_session.add(user)
    db_session.commit()
    
    # Try creating same user
    response = client.post('/api/auth/register', json={
        "username": "existing",
        "email": "other@example.com",
        "password": "password123",
        "full_name": "Other"
    })
    assert response.status_code == 409
    assert "already exists" in response.get_json()["error"]

def test_login_success(client, db_session):
    """Test successful login returns a JWT token."""
    user = User(username="loginuser", email="login@example.com", full_name="Login User")
    user.set_password("mypassword")
    db_session.add(user)
    db_session.commit()
    
    response = client.post('/api/auth/login', json={
        "username": "loginuser",
        "password": "mypassword"
    })
    assert response.status_code == 200
    data = response.get_json()
    assert "access_token" in data
    assert data["user"]["username"] == "loginuser"

def test_login_failure(client, db_session):
    """Test login fails with wrong password."""
    user = User(username="loginuser", email="login@example.com", full_name="Login User")
    user.set_password("mypassword")
    db_session.add(user)
    db_session.commit()
    
    response = client.post('/api/auth/login', json={
        "username": "loginuser",
        "password": "wrongpassword"
    })
    assert response.status_code == 401
