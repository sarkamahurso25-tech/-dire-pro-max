from getpass import getpass
from werkzeug.security import generate_password_hash
from config import Config
from models import db, User
from flask import Flask

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

with app.app_context():
    phone = input("Admin phone number: ").strip()
    full_name = input("Admin full name: ").strip()
    password = getpass("Create admin password: ")
    confirm = getpass("Confirm admin password: ")

    if not phone or not full_name or len(password) < 10:
        raise SystemExit("Phone, name guuti; password yoo xiqqaate 10 characters haa ta'u.")
    if password != confirm:
        raise SystemExit("Password wal hin simu.")

    user = User.query.filter_by(phone=phone).first()
    if user:
        user.full_name = full_name
        user.password_hash = generate_password_hash(password)
        user.role = "admin"
    else:
        user = User(
            full_name=full_name,
            phone=phone,
            password_hash=generate_password_hash(password),
            role="admin"
        )
        db.session.add(user)

    db.session.commit()
    print("ADMIN ACCOUNT READY")
