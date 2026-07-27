import os
from app import create_app
from app.extensions import db
from app.models.user import User

app = create_app()

with app.app_context():
    # Check if admin already exists
    if not User.query.filter_by(username='admin').first():
        print("Creating admin user...")
        admin = User(
            username='admin',
            email='admin@ajaokutasteel.com',
            full_name='System Administrator',
            is_admin=True
        )
        admin.set_password('password123')
        db.session.add(admin)
        db.session.commit()
        print("Admin user created (Username: admin, Password: password123)")
    else:
        print("Admin user already exists.")
