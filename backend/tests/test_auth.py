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

def test_register_first_user_is_admin(client, db_session):
    """The first account created on an empty system becomes the administrator."""
    response = client.post('/api/auth/register', json={
        "username": "first",
        "email": "first@example.com",
        "password": "password123",
        "full_name": "First User"
    })
    assert response.status_code == 201
    assert User.query.filter_by(username="first").first().is_admin is True

def test_register_requires_admin_once_users_exist(client, db_session, auth_headers):
    """Anonymous visitors cannot create accounts (or make themselves admin)."""
    payload = {
        "username": "intruder",
        "email": "intruder@example.com",
        "password": "password123",
        "full_name": "Intruder",
        "is_admin": True
    }
    assert client.post('/api/auth/register', json=payload).status_code == 401
    assert User.query.filter_by(username="intruder").first() is None

    # A non-admin account is refused too
    user = User(username="clerk", email="clerk@example.com", full_name="Clerk")
    user.set_password("pass")
    db_session.add(user)
    db_session.commit()
    token = client.post('/api/auth/login', json={"username": "clerk", "password": "pass"}).get_json()["access_token"]
    response = client.post('/api/auth/register', json=payload, headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403

    # An admin can
    assert client.post('/api/auth/register', json=payload, headers=auth_headers).status_code == 201

def test_register_duplicate(client, db_session, auth_headers):
    """Test duplicate registration fails."""
    # Try creating a user that already exists (the admin from auth_headers)
    response = client.post('/api/auth/register', json={
        "username": "testadmin",
        "email": "other@example.com",
        "password": "password123",
        "full_name": "Other"
    }, headers=auth_headers)
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
