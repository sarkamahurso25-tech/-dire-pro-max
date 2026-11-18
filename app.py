import os
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from sqlalchemy import inspect, text
from sqlalchemy.exc import IntegrityError
from functools import wraps
from types import SimpleNamespace

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash, jsonify
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
import secrets
import cloudinary
from cloudinary.uploader import upload as cloudinary_upload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from config import Config
from models import db, User, Product, Auction, Bid, Payment, AppSetting


app = Flask(__name__)
app.config.from_object(Config)
app.config["UPLOAD_FOLDER"] = os.path.join(
    app.root_path, "static", "uploads"
)
app.config["MAX_CONTENT_LENGTH"] = 12 * 1024 * 1024

os.makedirs(app.config["UPLOAD_FOLDER"], exist_ok=True)

db.init_app(app)

# Create missing database tables without deleting existing data.
with app.app_context():
    db.create_all()

    # Safely add bidder_name to existing databases without deleting records.
    bid_columns = {
        column["name"]
        for column in inspect(db.engine).get_columns("bid")
    }
    if "bidder_name" not in bid_columns:
        with db.engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE bid ADD COLUMN bidder_name VARCHAR(150)")
            )

    # Prevent duplicate non-empty Telebirr transaction references.
    with db.engine.begin() as connection:
        duplicate = connection.execute(text("""
            SELECT transaction_ref, COUNT(*) AS total
            FROM payment
            WHERE transaction_ref IS NOT NULL
              AND transaction_ref <> ''
            GROUP BY transaction_ref
            HAVING COUNT(*) > 1
            LIMIT 1
        """)).first()

        if duplicate:
            app.logger.warning(
                "Duplicate transaction references exist; "
                "unique index was not created. No records were deleted."
            )
        else:
            connection.execute(text("""
                CREATE UNIQUE INDEX IF NOT EXISTS
                uq_payment_transaction_ref_nonempty
                ON payment (transaction_ref)
                WHERE transaction_ref IS NOT NULL
                  AND transaction_ref <> ''
            """))
            app.logger.info(
                "Unique transaction reference index is ready."
            )

    app.logger.info("Database tables and bidder-name column initialized.")

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "admin_login"
login_manager.login_message = "Maaloo dura Admin seeni."
login_manager.login_message_category = "warning"

ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))


def admin_required(view):
    @wraps(view)
    @login_required
    def wrapped_view(*args, **kwargs):
        if current_user.role != "admin":
            flash("Fuula kana arguu hin dandeessu.", "danger")
            return redirect(url_for("home"))
        return view(*args, **kwargs)
    return wrapped_view


def get_telebirr_numbers():
    defaults = ["+251912997717", "+251914995880"]
    numbers = []

    for index, default in enumerate(defaults, start=1):
        setting = AppSetting.query.filter_by(
            key=f"telebirr_number_{index}"
        ).first()
        numbers.append(setting.value if setting else default)

    return numbers


@app.route("/admin/telebirr", methods=["POST"])
@admin_required
def update_telebirr():
    numbers = [
        request.form.get("telebirr_number_1", "").strip(),
        request.form.get("telebirr_number_2", "").strip()
    ]

    if any(not re.fullmatch(r"\+2519[0-9]{8}", number) for number in numbers):
        flash("Lakkoofsota Telebirr sirrii galchi.", "danger")
        return redirect(url_for("admin_dashboard"))

    if numbers[0] == numbers[1]:
        flash("Lakkoofsota Telebirr adda addaa galchi.", "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        for index, number in enumerate(numbers, start=1):
            key = f"telebirr_number_{index}"
            setting = AppSetting.query.filter_by(key=key).first()

            if setting is None:
                db.session.add(AppSetting(key=key, value=number))
            else:
                setting.value = number

        # Remove the old single-number setting.
        AppSetting.query.filter_by(key="telebirr_number").delete(
            synchronize_session=False
        )

        db.session.commit()
        flash("Lakkoofsota Telebirr lamaan milkaa'inaan haaromsite.", "success")
    except Exception:
        db.session.rollback()
        app.logger.exception("Telebirr numbers update failed")
        flash("Lakkoofsota Telebirr haaromsuun hin milkoofne.", "danger")

    return redirect(url_for("admin_dashboard"))


def allowed_file(filename):
    return (
        "." in filename
        and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS
    )


def parse_timer_seconds(timer_text):
    """Fakkeenya: 05d : 12h : 00m : 00s"""
    match = re.search(
        r"(?:(\d+)\s*d)?\s*:?\s*"
        r"(?:(\d+)\s*h)?\s*:?\s*"
        r"(?:(\d+)\s*m)?\s*:?\s*"
        r"(?:(\d+)\s*s)?",
        timer_text.lower()
    )
    if not match or not any(match.groups()):
        return 30 * 24 * 60 * 60

    days, hours, minutes, seconds = [
        int(value or 0) for value in match.groups()
    ]
    total = days * 86400 + hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else 30 * 24 * 60 * 60


def get_auction_item(auction):
    product = auction.product
    bids_count = Bid.query.filter_by(auction_id=auction.id).count()

    remaining = max(
        0, int((auction.end_time - datetime.utcnow()).total_seconds())
    )

    return SimpleNamespace(
        id=auction.id,
        title=auction.title,
        code=product.code or "",
        fee=product.service_fee or Decimal("0.00"),
        minimum_bid=max(Decimal("100.00"), Decimal(str(auction.minimum_bid or "100.00"))),
        timer=auction.timer_text or "",
        bids_count=bids_count,
        image=product.image or "default.png",
        remaining_seconds=remaining
    )


def get_confirmed_winner(auction_id):
    confirmed_refs = {
        row[0]
        for row in db.session.query(Payment.transaction_ref)
        .filter(
            Payment.auction_id == auction_id,
            Payment.status == "confirmed",
            Payment.transaction_ref.isnot(None),
            Payment.transaction_ref != ""
        ).all()
    }

    bids = Bid.query.filter_by(auction_id=auction_id).all()
    eligible = [bid for bid in bids if bid.tx_id in confirmed_refs]

    counts = {}
    for bid in eligible:
        counts[bid.amount] = counts.get(bid.amount, 0) + 1

    unique_amounts = [
        amount for amount, count in counts.items() if count == 1
    ]
    if not unique_amounts:
        return None

    highest = max(unique_amounts)
    winner_bid = next(
        bid for bid in eligible if bid.amount == highest
    )
    return SimpleNamespace(
        phone=winner_bid.phone,
        amount=winner_bid.amount,
        tx_id=winner_bid.tx_id
    )


@app.route("/")
def home():
    return render_template("index.html")


@app.route("/auctions")
def active_auctions():
    now = datetime.utcnow()
    rows = (
        Auction.query
        .filter(
            Auction.status == "active",
            Auction.end_time > now
        )
        .order_by(Auction.id.desc())
        .all()
    )
    auctions = [get_auction_item(row) for row in rows]
    return render_template("auctions.html", auctions=auctions)


@app.route("/auction/<int:item_id>", methods=["GET", "POST"])
def auction_detail(item_id):
    auction = db.session.get(Auction, item_id)

    if (
        not auction
        or auction.status != "active"
        or auction.start_time > datetime.utcnow()
        or auction.end_time <= datetime.utcnow()
    ):
        flash("Auction kun amma hin jiru ykn yeroo isaa xumureera.", "warning")
        return redirect(url_for("active_auctions"))

    item = get_auction_item(auction)

    if request.method == "POST":
        try:
            bidder_name = request.form.get("bidder_name", "").strip()
            user_phone = request.form.get("user_phone", "").strip()
            tx_id = request.form.get("tx_id", "").strip()
            selected_account = request.form.get("telebirr_account", "").strip()
            bid_amount = Decimal(request.form.get("bid_amount", ""))

            if not bidder_name or len(bidder_name) > 150:
                raise ValueError("Maqaa guutuu kee galchi.")
            if (
                not re.fullmatch(r"[+0-9() -]{7,30}", user_phone)
                or sum(ch.isdigit() for ch in user_phone) < 7
            ):
                raise ValueError("Lakkoofsa bilbilaa sirrii galchi.")
            if not tx_id or len(tx_id) > 150:
                raise ValueError("Telebirr Transaction ID sirrii galchi.")
            if selected_account not in get_telebirr_numbers():
                raise ValueError("Lakkoofsa Telebirr sirrii filadhu.")
            if (
                not bid_amount.is_finite()
                or bid_amount <= 0
                or bid_amount > Decimal("9999999999.99")
                or bid_amount.as_tuple().exponent < -2
            ):
                raise ValueError("Bid amount sirrii galchi.")
            if bid_amount < item.minimum_bid:
                raise ValueError(
                    f"Minimum Bid {item.minimum_bid} Br dha. "
                    "Kana ol ykn walqixa galchi."
                )

            existing_payment = Payment.query.filter_by(
                transaction_ref=tx_id
            ).first()
            if existing_payment:
                flash("Transaction ID kanaan duraan galmaa'eera.", "danger")
                return redirect(url_for("auction_detail", item_id=item_id))

            bid = Bid(
                auction_id=auction.id,
                user_id=None,
                amount=bid_amount,
                phone=user_phone,
                bidder_name=bidder_name,
                tx_id=tx_id
            )

            payment = Payment(
                user_id=None,
                auction_id=auction.id,
                amount=item.fee,
                provider="telebirr",
                telebirr_account=selected_account,
                transaction_ref=tx_id,
                status="pending"
            )

            db.session.add(bid)
            db.session.add(payment)
            db.session.commit()

            flash(
                "Bid fi Transaction ID galmaa'eera. "
                "Kaffaltiin Adminiin hanga mirkanaa'utti Pending dha.",
                "success"
            )
            return redirect(url_for("auction_detail", item_id=item_id))

        except (ValueError, ArithmeticError):
            db.session.rollback()
            flash("Maaloo odeeffannoo sirrii galchi.", "danger")
        except IntegrityError:
            db.session.rollback()
            flash("Transaction ID kanaan duraan galmaa'eera.", "danger")
            return redirect(url_for("auction_detail", item_id=item_id))
        except Exception:
            db.session.rollback()
            app.logger.exception("Bid galmeessuu irratti dogoggora")
            flash("Galmeessuun hin milkoofne. Irra deebi'i.", "danger")

    return render_template(
        "detail.html",
        item=item,
        telebirr_numbers=get_telebirr_numbers()
    )


@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if current_user.is_authenticated and current_user.role == "admin":
        return redirect(url_for("admin_dashboard"))

    if request.method == "POST":
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")

        user = User.query.filter_by(phone=phone).first()

        if (
            user
            and user.role == "admin"
            and check_password_hash(user.password_hash, password)
        ):
            login_user(user)
            flash("Admin seenteetta.", "success")
            return redirect(url_for("admin_dashboard"))

        flash("Phone ykn password sirrii miti.", "danger")

    return render_template("admin_login.html")


@app.route("/admin/logout")
@login_required
def admin_logout():
    logout_user()
    flash("Baateetta.", "success")
    return redirect(url_for("home"))


@app.route("/admin", methods=["GET", "POST"])
@admin_required
def admin_dashboard():
    if request.method == "POST":
        try:
            title = request.form.get("title", "").strip()
            code = request.form.get("code", "").strip()
            fee = Decimal(request.form.get("fee", ""))
            minimum_bid = Decimal(request.form.get("minimum_bid", ""))
            timer_text = request.form.get("timer", "").strip()

            if not title or not code or not timer_text:
                raise ValueError("Odeeffannoo dirqamaa guuti.")
            if not fee.is_finite() or fee < 0:
                raise ValueError("Service Fee sirrii galchi.")
            if not minimum_bid.is_finite() or minimum_bid < Decimal("100.00"):
                raise ValueError("Minimum Bid xiqqaateen 100 Birr ta'uu qaba.")

            image_filename = "default.png"
            uploaded = request.files.get("image")

            if uploaded and uploaded.filename:
                if not allowed_file(uploaded.filename):
                    raise ValueError("Suuraa JPG, PNG ykn WEBP qofa fayyadami.")

                cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME")
                api_key = os.getenv("CLOUDINARY_API_KEY")
                api_secret = os.getenv("CLOUDINARY_API_SECRET")

                if not all((cloud_name, api_key, api_secret)):
                    raise ValueError("Cloudinary configuration is missing on server.")

                cloudinary.config(
                    cloud_name=cloud_name,
                    api_key=api_key,
                    api_secret=api_secret,
                    secure=True,
                )

                result = cloudinary_upload(
                    uploaded,
                    folder="dire-pro-max/products",
                    resource_type="image",
                )
                image_filename = result["secure_url"]

            now = datetime.utcnow()
            end_time = now + timedelta(
                seconds=parse_timer_seconds(timer_text)
            )

            product = Product(
                name=title,
                description="",
                image=image_filename,
                starting_price=Decimal("0.00"),
                code=code,
                service_fee=fee
            )
            db.session.add(product)
            db.session.flush()

            auction = Auction(
                product_id=product.id,
                title=title,
                start_time=now,
                end_time=end_time,
                status="active",
                timer_text=timer_text,
                minimum_bid=minimum_bid
            )
            db.session.add(auction)
            db.session.commit()

            flash("Meeshaan haaraan milkaa'inaan dabalameera!", "success")
            return redirect(url_for("admin_dashboard"))

        except (ValueError, ArithmeticError) as error:
            db.session.rollback()
            flash(str(error), "danger")
        except Exception:
            db.session.rollback()
            app.logger.exception("Auction uumuu irratti dogoggora")
            flash("Auction dabaluu hin dandeenye.", "danger")

    auction_rows = Auction.query.order_by(Auction.id.desc()).all()
    results = []
    total_revenue = Decimal("0.00")

    # Build payment-status lookup without changing existing records.
    payment_rows = Payment.query.all()
    payment_status_by_key = {
        (payment.auction_id, payment.transaction_ref): payment.status
        for payment in payment_rows
        if payment.transaction_ref
    }

    winner_by_auction = {}

    for auction in auction_rows:
        item = get_auction_item(auction)
        winner = get_confirmed_winner(auction.id)
        winner_by_auction[auction.id] = winner

        revenue = (
            db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
            .filter(
                Payment.auction_id == auction.id,
                Payment.status == "confirmed"
            ).scalar()
        )
        total_revenue += Decimal(str(revenue))

        auction_bid_rows = (
            Bid.query
            .filter_by(auction_id=auction.id)
            .order_by(Bid.created_at.desc())
            .all()
        )

        bidders = []
        for bid_row in auction_bid_rows:
            is_winner = bool(
                winner
                and winner.tx_id
                and bid_row.tx_id == winner.tx_id
                and bid_row.amount == winner.amount
            )
            bidders.append(SimpleNamespace(
                name=bid_row.bidder_name or bid_row.phone or "Maqaa hin galmoofne",
                phone=bid_row.phone or "",
                amount=bid_row.amount,
                tx_id=bid_row.tx_id or "",
                payment_status=payment_status_by_key.get(
                    (auction.id, bid_row.tx_id), "not found"
                ),
                is_winner=is_winner
            ))

        results.append(SimpleNamespace(
            item=item,
            winner=winner,
            revenue=revenue,
            bidders=bidders
        ))

    bid_rows = Bid.query.order_by(Bid.created_at.desc()).all()
    auction_titles = {
        auction.id: auction.title for auction in auction_rows
    }

    bids = []
    for bid_row in bid_rows:
        winner = winner_by_auction.get(bid_row.auction_id)
        is_winner = bool(
            winner
            and winner.tx_id
            and bid_row.tx_id == winner.tx_id
            and bid_row.amount == winner.amount
        )
        bids.append(SimpleNamespace(
            item_id=bid_row.auction_id,
            item_title=auction_titles.get(bid_row.auction_id, "Unknown Auction"),
            bidder_name=bid_row.bidder_name or bid_row.phone or "Maqaa hin galmoofne",
            phone=bid_row.phone or "",
            amount=bid_row.amount,
            tx_id=bid_row.tx_id or "",
            payment_status=payment_status_by_key.get(
                (bid_row.auction_id, bid_row.tx_id), "not found"
            ),
            is_winner=is_winner
        ))

    payments = (
        Payment.query
        .order_by(Payment.created_at.desc())
        .all()
    )

    return render_template(
        "admin.html",
        auctions=[get_auction_item(row) for row in auction_rows],
        bids=bids,
        results=results,
        total_revenue=total_revenue,
        payments=payments,
        telebirr_numbers=get_telebirr_numbers()
    )


@app.route("/admin/payment/<int:payment_id>/confirm", methods=["POST"])
@admin_required
def confirm_payment(payment_id):
    payment = db.session.get(Payment, payment_id)

    if not payment:
        flash("Kaffaltiin hin argamne.", "danger")
        return redirect(url_for("admin_dashboard"))

    if payment.status == "confirmed":
        flash("Kaffaltiin kun duraan mirkanaa'eera.", "info")
        return redirect(url_for("admin_dashboard"))

    if not payment.transaction_ref:
        flash("Transaction ID hin qabu; kaffaltii kana hin mirkaneessine.", "danger")
        return redirect(url_for("admin_dashboard"))

    matching_bid = Bid.query.filter_by(
        auction_id=payment.auction_id,
        tx_id=payment.transaction_ref
    ).first()

    if not matching_bid:
        flash("Payment kanaaf bid wal-simu hin argamne.", "danger")
        return redirect(url_for("admin_dashboard"))

    try:
        payment.status = "confirmed"
        db.session.commit()
        flash("Kaffaltiin mirkanaa'eera.", "success")
    except Exception:
        db.session.rollback()
        app.logger.exception("Payment confirmation failed")
        flash("Kaffaltii mirkaneessuun hin milkoofne.", "danger")

    return redirect(url_for("admin_dashboard"))


@app.route("/admin/delete/<int:item_id>", methods=["POST"])
@admin_required
def delete_auction(item_id):
    auction = db.session.get(Auction, item_id)
    if auction:
        # Galmee bid/payment seenaa ta'e hin haqnu.
        auction.status = "cancelled"
        db.session.commit()
        flash("Auction hojii irraa dhaabbateera.", "warning")
    else:
        flash("Auction hin argamne.", "danger")

    return redirect(url_for("admin_dashboard"))



@app.route("/internal/admin-password-reset", methods=["POST"])
def secure_admin_password_reset():
    reset_token = os.environ.get("ADMIN_RESET_TOKEN", "")
    supplied_token = request.form.get("token", "")

    if not reset_token or not secrets.compare_digest(
        supplied_token, reset_token
    ):
        return "Unauthorized", 401

    phone = request.form.get("phone", "").strip()
    full_name = request.form.get("full_name", "").strip()
    password = request.form.get("password", "")

    if not phone or not full_name or len(password) < 10:
        return "Phone, full name and password of at least 10 characters are required.", 400

    try:
        user = User.query.filter_by(phone=phone).first()

        if user:
            user.full_name = full_name
            user.role = "admin"
            user.password_hash = generate_password_hash(password)
        else:
            user = User(
                full_name=full_name,
                phone=phone,
                password_hash=generate_password_hash(password),
                role="admin"
            )
            db.session.add(user)

        db.session.commit()
        app.logger.warning("Admin account setup completed.")
        return "ADMIN ACCOUNT READY", 200

    except Exception:
        db.session.rollback()
        app.logger.exception("Admin account setup failed.")
        return "Admin account setup failed.", 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)


# ============================================================
# DIRE PRO MAX - TELEBIRR MINI-APP JSON API
# Existing website and admin routes remain unchanged.
# ============================================================

def miniapp_auction_json(auction):
    product = auction.product
    item = get_auction_item(auction)

    if product.image and product.image.startswith(("https://", "http://")):
        image_url = product.image
    elif product.image:
        image_url = url_for(
            "static",
            filename="uploads/" + product.image,
            _external=True
        )
    else:
        image_url = None

    return {
        "id": auction.id,
        "product_id": product.id,
        "title": auction.title,
        "product_name": product.name,
        "code": product.code or "",
        "description": product.description or "",
        "image_url": image_url,
        "service_fee": str(product.service_fee or Decimal("0.00")),
        "starting_price": str(product.starting_price or Decimal("0.00")),
        "minimum_bid": str(item.minimum_bid),
        "bids_count": item.bids_count,
        "status": auction.status,
        "start_time": auction.start_time.isoformat(),
        "end_time": auction.end_time.isoformat(),
        "remaining_seconds": item.remaining_seconds,
    }


def miniapp_active_auctions():
    now = datetime.utcnow()
    return (
        Auction.query
        .filter(
            Auction.status == "active",
            Auction.start_time <= now,
            Auction.end_time > now
        )
        .order_by(Auction.id.desc())
        .all()
    )


@app.route("/api/miniapp/home", methods=["GET"])
def miniapp_home_api():
    auctions = miniapp_active_auctions()
    return jsonify({
        "success": True,
        "app": "DIRE PRO MAX",
        "message": "Welcome to DIRE PRO MAX",
        "active_auctions_count": len(auctions),
        "auctions": [miniapp_auction_json(a) for a in auctions[:6]]
    })


@app.route("/api/miniapp/auctions", methods=["GET"])
def miniapp_auctions_api():
    auctions = miniapp_active_auctions()
    return jsonify({
        "success": True,
        "count": len(auctions),
        "auctions": [miniapp_auction_json(a) for a in auctions]
    })


@app.route("/api/miniapp/auction/<int:item_id>", methods=["GET"])
def miniapp_auction_detail_api(item_id):
    auction = db.session.get(Auction, item_id)

    if not auction:
        return jsonify({
            "success": False,
            "error": "Auction not found"
        }), 404

    return jsonify({
        "success": True,
        "auction": miniapp_auction_json(auction),
        "telebirr_accounts": get_telebirr_numbers()
    })


@app.route("/api/miniapp/auction/<int:item_id>/bid", methods=["POST"])
def miniapp_place_bid_api(item_id):
    auction = db.session.get(Auction, item_id)

    if (
        not auction
        or auction.status != "active"
        or auction.start_time > datetime.utcnow()
        or auction.end_time <= datetime.utcnow()
    ):
        return jsonify({
            "success": False,
            "error": "Auction is not currently available"
        }), 404

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({
            "success": False,
            "error": "JSON request body is required"
        }), 400

    try:
        text_fields = (
            "bidder_name", "phone", "transaction_id", "telebirr_account"
        )
        if any(not isinstance(data.get(key), str) for key in text_fields):
            raise ValueError("Text fields must be strings.")

        bidder_name = data["bidder_name"].strip()
        user_phone = data["phone"].strip()
        tx_id = data["transaction_id"].strip()
        selected_account = data["telebirr_account"].strip()

        raw_amount = data.get("bid_amount")
        if raw_amount is None or isinstance(raw_amount, bool):
            raise ValueError("Bid amount is required.")
        bid_amount = Decimal(str(raw_amount))

        item = get_auction_item(auction)

        if not bidder_name or len(bidder_name) > 150:
            raise ValueError("Enter a valid full name.")

        if (
            not re.fullmatch(r"[+0-9() -]{7,30}", user_phone)
            or sum(ch.isdigit() for ch in user_phone) < 7
        ):
            raise ValueError("Enter a valid phone number.")

        if not tx_id or len(tx_id) > 150:
            raise ValueError("Enter a valid Telebirr transaction ID.")

        if selected_account not in get_telebirr_numbers():
            raise ValueError("Select a valid Telebirr account.")

        if (
            not bid_amount.is_finite()
            or bid_amount <= 0
            or bid_amount > Decimal("9999999999.99")
            or bid_amount.as_tuple().exponent < -2
        ):
            raise ValueError("Enter a valid bid amount.")

        if bid_amount < item.minimum_bid:
            raise ValueError(
                f"Minimum bid is {item.minimum_bid} Br."
            )

        existing_payment = Payment.query.filter_by(
            transaction_ref=tx_id
        ).first()

        if existing_payment:
            return jsonify({
                "success": False,
                "error": "This transaction ID has already been submitted."
            }), 409

        # Refresh auction state immediately before recording the bid.
        db.session.refresh(auction)
        now = datetime.utcnow()

        if (
            auction.status != "active"
            or auction.start_time > now
            or auction.end_time <= now
        ):
            return jsonify({
                "success": False,
                "error": "This auction has ended or is not open for bidding."
            }), 409

        bid = Bid(
            auction_id=auction.id,
            user_id=None,
            amount=bid_amount,
            phone=user_phone,
            bidder_name=bidder_name,
            tx_id=tx_id
        )

        payment = Payment(
            user_id=None,
            auction_id=auction.id,
            amount=item.fee,
            provider="telebirr",
            telebirr_account=selected_account,
            transaction_ref=tx_id,
            status="pending"
        )

        db.session.add(bid)
        db.session.add(payment)
        db.session.commit()

        return jsonify({
            "success": True,
            "message": "Bid submitted. Payment is pending admin verification.",
            "bid_status": "submitted",
            "payment_status": "pending"
        }), 201

    except (ValueError, ArithmeticError):
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": "Please check the submitted information."
        }), 400

    except IntegrityError:
        db.session.rollback()
        return jsonify({
            "success": False,
            "error": "This transaction ID has already been submitted."
        }), 409

    except Exception:
        db.session.rollback()
        app.logger.exception("Mini-App bid submission failed")
        return jsonify({
            "success": False,
            "error": "Bid submission failed. Please try again."
        }), 500


@app.route("/miniapp", methods=["GET"])
def miniapp_page():
    return render_template("miniapp.html")


@app.route("/miniapp/auction/<int:item_id>", methods=["GET"])
def miniapp_auction_page(item_id):
    return render_template("miniapp_detail.html")
