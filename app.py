import os
import re
import uuid
from datetime import datetime, timedelta
from decimal import Decimal
from functools import wraps
from types import SimpleNamespace

from flask import (
    Flask, render_template, request, redirect,
    url_for, flash
)
from flask_login import (
    LoginManager, login_user, logout_user,
    login_required, current_user
)
from werkzeug.security import check_password_hash
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
        minimum_bid=auction.minimum_bid or Decimal("1.00"),
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
            Payment.transaction_ref.isnot(None)
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

    lowest = min(unique_amounts)
    winner_bid = next(
        bid for bid in eligible if bid.amount == lowest
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
        or auction.end_time <= datetime.utcnow()
    ):
        flash("Auction kun amma hin jiru ykn yeroo isaa xumureera.", "warning")
        return redirect(url_for("active_auctions"))

    item = get_auction_item(auction)

    if request.method == "POST":
        try:
            user_phone = request.form.get("user_phone", "").strip()
            tx_id = request.form.get("tx_id", "").strip()
            selected_account = request.form.get("telebirr_account", "").strip()
            bid_amount = Decimal(request.form.get("bid_amount", ""))

            if not user_phone or len(user_phone) > 30:
                raise ValueError("Lakkoofsa bilbilaa sirrii galchi.")
            if not tx_id or len(tx_id) > 150:
                raise ValueError("Telebirr Transaction ID sirrii galchi.")
            if selected_account not in get_telebirr_numbers():
                raise ValueError("Lakkoofsa Telebirr sirrii filadhu.")
            if not bid_amount.is_finite() or bid_amount <= 0:
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
            if not minimum_bid.is_finite() or minimum_bid <= 0:
                raise ValueError("Minimum Bid 0 ol ta'uu qaba.")

            image_filename = "default.png"
            uploaded = request.files.get("image")

            if uploaded and uploaded.filename:
                if not allowed_file(uploaded.filename):
                    raise ValueError("Suuraa JPG, PNG ykn WEBP qofa fayyadami.")

                safe_name = secure_filename(uploaded.filename)
                extension = safe_name.rsplit(".", 1)[1].lower()
                image_filename = f"{uuid.uuid4().hex}.{extension}"
                uploaded.save(
                    os.path.join(app.config["UPLOAD_FOLDER"], image_filename)
                )

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

    for auction in auction_rows:
        item = get_auction_item(auction)
        revenue = (
            db.session.query(db.func.coalesce(db.func.sum(Payment.amount), 0))
            .filter(
                Payment.auction_id == auction.id,
                Payment.status == "confirmed"
            ).scalar()
        )
        total_revenue += Decimal(str(revenue))
        results.append(SimpleNamespace(
            item=item,
            winner=get_confirmed_winner(auction.id),
            revenue=revenue
        ))

    bid_rows = Bid.query.order_by(Bid.created_at.desc()).all()
    bids = [
        SimpleNamespace(
            item_id=row.auction_id,
            phone=row.phone or "",
            amount=row.amount,
            tx_id=row.tx_id or ""
        )
        for row in bid_rows
    ]

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

    payment.status = "confirmed"
    db.session.commit()
    flash("Kaffaltiin mirkanaa'eera.", "success")
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


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
