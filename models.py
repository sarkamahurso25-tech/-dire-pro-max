from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = "user"

    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(150), nullable=False)
    phone = db.Column(db.String(30), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="customer")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Product(db.Model):
    __tablename__ = "product"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    image = db.Column(db.String(255))
    starting_price = db.Column(db.Numeric(12, 2), default=0)
    code = db.Column(db.String(50))
    service_fee = db.Column(db.Numeric(12, 2), default=0)


class Auction(db.Model):
    __tablename__ = "auction"

    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(
        db.Integer, db.ForeignKey("product.id")
    )
    title = db.Column(db.String(200), nullable=False)
    start_time = db.Column(db.DateTime, nullable=False)
    end_time = db.Column(db.DateTime, nullable=False)
    status = db.Column(db.String(20), default="upcoming")
    timer_text = db.Column(db.String(100))
    minimum_bid = db.Column(db.Numeric(12, 2), nullable=False, default=100.00)

    product = db.relationship("Product", backref="auctions")


class Bid(db.Model):
    __tablename__ = "bid"

    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id")
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    phone = db.Column(db.String(30))
    bidder_name = db.Column(db.String(150), nullable=True)
    tx_id = db.Column(db.String(150))


class Payment(db.Model):
    __tablename__ = "payment"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True
    )
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id")
    )
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    provider = db.Column(db.String(30), default="telebirr")
    telebirr_account = db.Column(db.String(20), nullable=True)
    transaction_ref = db.Column(db.String(150))
    status = db.Column(db.String(20), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Winner(db.Model):
    __tablename__ = "winner"

    id = db.Column(db.Integer, primary_key=True)
    auction_id = db.Column(
        db.Integer, db.ForeignKey("auction.id")
    )
    user_id = db.Column(
        db.Integer, db.ForeignKey("user.id"), nullable=True
    )
    winning_amount = db.Column(db.Numeric(12, 2))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class AppSetting(db.Model):
    __tablename__ = "app_setting"

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.String(255), nullable=False)
