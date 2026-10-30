import os
import uuid
from functools import wraps

import pymysql
from dotenv import load_dotenv
from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from pymysql.cursors import DictCursor
from werkzeug.security import check_password_hash, generate_password_hash

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-key-change-me")

# 🌟 DYNAMIC DATABASE CONNECTION WITH AUTOCOMMIT
def db_connect():
    # 🔴 EDIT HERE: Put your actual MySQL Workbench password between the quotes (e.g., "root" or "1234")
    db_password = os.environ.get("MYSQL_PASSWORD", "YOUR_WORKBENCH_PASSWORD_HERE") 
    
    # 🔴 EDIT HERE: Check the left sidebar (Schemas) in Workbench. Ensure this matches your schema name perfectly.
    db_name = os.environ.get("MYSQL_DATABASE", "ecommerce_management") 
    
    return pymysql.connect(
        host=os.environ.get("MYSQL_HOST", "localhost"),
        user=os.environ.get("MYSQL_USER", "root"),
        password=db_password,
        database=db_name,
        cursorclass=DictCursor,
        autocommit=True,  # ✨ Pushes data to Workbench instantly without requiring a manual commit!
        charset="utf8mb4",
    )

def wants_json():
    accept = request.headers.get("Accept", "")
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in accept
    )

def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        user_id = session.get("user_id")
        if not user_id:
            if wants_json():
                return jsonify({"ok": False, "error": "login_required"}), 401
            return redirect(url_for("login", next=request.path))

        conn = db_connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                if not cur.fetchone():
                    session.clear()
                    if wants_json():
                        return jsonify({"ok": False, "error": "login_required"}), 401
                    return redirect(url_for("login", next=request.path))
        except Exception as e:
            print(f"❌ Login Required Check Error: {e}")
            session.clear()
            if wants_json():
                return jsonify({"ok": False, "error": "login_required"}), 401
            return redirect(url_for("login", next=request.path))
        finally:
            conn.close()

        return fn(*args, **kwargs)

    return wrapper

@app.context_processor
def inject_global_context():
    categories = []
    cart_count = 0
    selected_category_id = request.args.get("category", type=int)
    user_id = session.get("user_id")

    try:
        conn = db_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM productcategory ORDER BY name")
            categories = cur.fetchall()
            if user_id:
                cur.execute("SELECT id FROM users WHERE id = %s", (user_id,))
                if cur.fetchone():
                    cart_count = get_cart_count(conn, user_id)
                else:
                    session.clear()
                    user_id = None
        conn.close()
    except Exception as e:
        print(f"❌ Global Context Error: {e}")

    return {
        "nav_categories": categories,
        "selected_category_id": selected_category_id,
        "cart_count": cart_count,
    }

def get_cart_count(conn, user_id):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT COALESCE(SUM(cp.quantity), 0) AS cnt
            FROM cart c
            LEFT JOIN cartproducts cp ON cp.cart_id = c.id
            WHERE c.user_id = %s
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return int(row["cnt"]) if row else 0

def get_or_create_cart_id(conn, user_id):
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM cart WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        if row:
            return int(row["id"])
        cur.execute("INSERT INTO cart (user_id) VALUES (%s)", (user_id,))
        return int(cur.lastrowid)

@app.get("/")
def index():
    category_id = request.args.get("category", type=int)
    user_id = session.get("user_id")

    try:
        conn = db_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT id, name FROM productcategory ORDER BY name")
            categories = cur.fetchall()

            params = []
            where = ""
            if category_id:
                where = "WHERE p.category_id = %s"
                params.append(category_id)

            cur.execute(
                f"""
                SELECT
                  p.id,
                  p.name,
                  p.description,
                  p.price,
                  p.image_url,
                  p.product_url,
                  p.stock,
                  pc.id AS category_id,
                  pc.name AS category_name
                FROM products p
                JOIN productcategory pc ON pc.id = p.category_id
                {where}
                ORDER BY p.created_at DESC, p.id DESC
                """,
                params,
            )
            products = cur.fetchall()

            cart_count = 0
            if user_id:
                cart_count = get_cart_count(conn, user_id)
        conn.close()
        
        return render_template(
            "index.html",
            categories=categories,
            products=products,
            selected_category_id=category_id,
            cart_count=cart_count,
        )
    except Exception as e:
        print(f"❌ Index Page Error: {e}")
        return "Database Connection Error! Check your VS Code Terminal logs.", 500

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template(
            "login.html",
            mode="login",
            next_url=request.args.get("next") or "",
            cart_count=0,
        )

    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not email or not password:
        flash("Email and password are required.", "error")
        return render_template("login.html", mode="login", next_url="", cart_count=0)

    try:
        conn = db_connect()
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, name, email, password_hash FROM users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()
        conn.close()

        if not user or not check_password_hash(user["password_hash"], password):
            flash("Invalid credentials.", "error")
            return render_template("login.html", mode="login", next_url="", cart_count=0)

        session["user_id"] = int(user["id"])
        session["user_name"] = user["name"]

        next_url = request.form.get("next") or ""
        return redirect(next_url or url_for("index"))
    except Exception as e:
        print(f"❌ Login Route Error: {e}")
        flash("Login failed due to database issue.", "error")
        return render_template("login.html", mode="login", next_url="", cart_count=0)

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "GET":
        if session.get("user_id"):
            return redirect(url_for("index"))
        return render_template("login.html", mode="signup", next_url="", cart_count=0)

    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip().lower()
    password = request.form.get("password") or ""

    if not name or not email or not password:
        flash("Name, email, and password are required.", "error")
        return render_template("login.html", mode="signup", next_url="", cart_count=0)

    if len(password) < 6:
        flash("Password must be at least 6 characters.", "error")
        return render_template("login.html", mode="signup", next_url="", cart_count=0)

    try:
        conn = db_connect()
        with conn.cursor() as cur:
            password_hash = generate_password_hash(password)
            try:
                cur.execute(
                    "INSERT INTO users (name, email, password_hash) VALUES (%s, %s, %s)",
                    (name, email, password_hash),
                )
                user_id = int(cur.lastrowid)
                cur.execute("INSERT INTO cart (user_id) VALUES (%s)", (user_id,))
                print(f"🎉 SUCCESS: User {name} automatically inserted into DB!")
            except pymysql.IntegrityError:
                flash("An account with this email already exists.", "error")
                return render_template("login.html", mode="signup", next_url="", cart_count=0)
        conn.close()

        session["user_id"] = user_id
        session["user_name"] = name
        return redirect(url_for("index"))
    except Exception as e:
        print(f"❌ Signup Route Error: {e}")
        flash("Signup failed. Check database connection parameters.", "error")
        return render_template("login.html", mode="signup", next_url="", cart_count=0)

@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.get("/cart")
@login_required
def view_cart():
    user_id = session["user_id"]
    try:
        conn = db_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM cart WHERE user_id = %s", (user_id,))
            cart_row = cur.fetchone()
            cart_id = int(cart_row["id"]) if cart_row else None

            items = []
            subtotal = 0.0
            if cart_id:
                cur.execute(
                    """
                    SELECT
                      p.id AS product_id,
                      p.name,
                      p.price,
                      p.image_url,
                      cp.quantity,
                      (p.price * cp.quantity) AS line_total
                    FROM cartproducts cp
                    JOIN products p ON p.id = cp.product_id
                    WHERE cp.cart_id = %s
                    ORDER BY p.name
                    """,
                    (cart_id,),
                )
                items = cur.fetchall()
                subtotal = float(sum(float(i["line_total"]) for i in items))

            cart_count = get_cart_count(conn, user_id)
        conn.close()
        return render_template("cart.html", items=items, subtotal=subtotal, cart_count=cart_count)
    except Exception as e:
        print(f"❌ View Cart Error: {e}")
        return redirect(url_for("index"))

@app.post("/cart/add/<int:product_id>")
@login_required
def cart_add(product_id):
    user_id = session["user_id"]
    try:
        conn = db_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM products WHERE id = %s", (product_id,))
            if not cur.fetchone():
                if wants_json():
                    return jsonify({"ok": False, "error": "not_found"}), 404
                flash("Product not found.", "error")
                return redirect(url_for("index"))

            cart_id = get_or_create_cart_id(conn, user_id)
            cur.execute(
                """
                INSERT INTO cartproducts (cart_id, product_id, quantity)
                VALUES (%s, %s, 1)
                ON DUPLICATE KEY UPDATE quantity = quantity + 1
                """,
                (cart_id, product_id),
            )
            cur.execute(
                "SELECT quantity FROM cartproducts WHERE cart_id = %s AND product_id = %s",
                (cart_id, product_id),
            )
            line = cur.fetchone()
            cart_count = get_cart_count(conn, user_id)
        conn.close()

        if wants_json():
            return jsonify({
                "ok": True,
                "cart_count": cart_count,
                "product_id": product_id,
                "line_quantity": int(line["quantity"]) if line else 0,
            })

        flash("Added to cart.", "success")
        return redirect(request.referrer or url_for("index"))
    except Exception as e:
        print(f"❌ Add to Cart Error: {e}")
        return jsonify({"ok": False, "error": "db_error"}), 500

@app.post("/cart/remove/<int:product_id>")
@login_required
def cart_remove(product_id):
    user_id = session["user_id"]
    try:
        conn = db_connect()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM cart WHERE user_id = %s", (user_id,))
            cart_row = cur.fetchone()
            if not cart_row:
                if wants_json():
                    return jsonify({"ok": False, "error": "empty_cart"}), 400
                flash("Cart is empty.", "error")
                return redirect(url_for("view_cart"))

            cart_id = int(cart_row["id"])
            cur.execute(
                "SELECT quantity FROM cartproducts WHERE cart_id = %s AND product_id = %s",
                (cart_id, product_id),
            )
            row = cur.fetchone()
            if not row:
                if wants_json():
                    return jsonify({"ok": False, "error": "not_in_cart"}), 400
                flash("Item not found in cart.", "error")
                return redirect(url_for("view_cart"))

            qty = int(row["quantity"])
            if qty <= 1:
                cur.execute(
                    "DELETE FROM cartproducts WHERE cart_id = %s AND product_id = %s",
                    (cart_id, product_id),
                )
                line_qty = 0
            else:
                cur.execute(
                    "UPDATE cartproducts SET quantity = quantity - 1 WHERE cart_id = %s AND product_id = %s",
                    (cart_id, product_id),
                )
                line_qty = qty - 1

            cart_count = get_cart_count(conn, user_id)
        conn.close()

        if wants_json():
            return jsonify({
                "ok": True,
                "cart_count": cart_count,
                "product_id": product_id,
                "line_quantity": line_qty,
            })

        flash("Updated cart.", "success")
        return redirect(request.referrer or url_for("view_cart"))
    except Exception as e:
        print(f"❌ Remove Cart Error: {e}")
        return jsonify({"ok": False, "error": "db_error"}), 500

@app.post("/checkout")
@login_required
def checkout():
    user_id = session["user_id"]
    full_name = (request.form.get("full_name") or "").strip()
    line1 = (request.form.get("line1") or "").strip()
    line2 = (request.form.get("line2") or "").strip()
    city = (request.form.get("city") or "").strip()
    state = (request.form.get("state") or "").strip()
    postal_code = (request.form.get("postal_code") or "").strip()
    country = (request.form.get("country") or "").strip()
    phone = (request.form.get("phone") or "").strip()
    payment_method = (request.form.get("payment_method") or "cod").strip().lower()

    if payment_method not in {"cod", "card", "upi"}:
        payment_method = "cod"

    if not all([full_name, line1, city, state, postal_code, country]):
        flash("Please fill in all required shipping fields.", "error")
        return redirect(url_for("view_cart"))

    try:
        conn = db_connect()
        conn.begin()
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM cart WHERE user_id = %s FOR UPDATE", (user_id,))
            cart_row = cur.fetchone()
            if not cart_row:
                raise ValueError("empty_cart")

            cart_id = int(cart_row["id"])
            cur.execute(
                """
                SELECT cp.product_id, cp.quantity, p.price, p.stock
                FROM cartproducts cp
                JOIN products p ON p.id = cp.product_id
                WHERE cp.cart_id = %s FOR UPDATE
                """,
                (cart_id,),
            )
            cart_items = cur.fetchall()
            if not cart_items:
                raise ValueError("empty_cart")

            subtotal = float(sum(float(i["price"]) * int(i["quantity"]) for i in cart_items))

            cur.execute(
                """
                INSERT INTO address (user_id, full_name, line1, line2, city, state, postal_code, country, phone)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (user_id, full_name, line1, line2 or None, city, state, postal_code, country, phone or None),
            )
            address_id = int(cur.lastrowid)

            cur.execute(
                "INSERT INTO orders (user_id, address_id, status, subtotal) VALUES (%s, %s, 'pending', %s)",
                (user_id, address_id, subtotal),
            )
            order_id = int(cur.lastrowid)

            for item in cart_items:
                product_id = int(item["product_id"])
                qty = int(item["quantity"])
                unit_price = float(item["price"])
                stock = int(item["stock"])

                if stock < qty:
                    raise ValueError("insufficient_stock")

                cur.execute(
                    "INSERT INTO orderproducts (order_id, product_id, quantity, unit_price) VALUES (%s, %s, %s, %s)",
                    (order_id, product_id, qty, unit_price),
                )
                cur.execute("UPDATE products SET stock = stock - %s WHERE id = %s", (qty, product_id))

            cur.execute(
                "INSERT INTO trackingdetail (order_id, status, details) VALUES (%s, %s, %s)",
                (order_id, "Order Placed", "We have received your order."),
            )

            transaction_ref = uuid.uuid4().hex
            cur.execute(
                "INSERT INTO payments (order_id, amount, method, status, transaction_ref) VALUES (%s, %s, %s, 'paid', %s)",
                (order_id, subtotal, payment_method, transaction_ref),
            )
            cur.execute("UPDATE orders SET status = 'paid' WHERE id = %s", (order_id,))
            cur.execute("DELETE FROM cartproducts WHERE cart_id = %s", (cart_id,))

        conn.commit()
        conn.close()
        flash(f"Order placed successfully. Order ID: {order_id}", "success")
        return redirect(url_for("index"))
        
        
    except ValueError as e:
        if 'conn' in locals(): conn.rollback(); conn.close()
        if str(e) == "insufficient_stock":
            flash("One or more items are out of stock.", "error")
        else:
            flash("Your cart is empty.", "error")
        return redirect(url_for("view_cart"))
    except Exception as e:
        if 'conn' in locals(): conn.rollback(); conn.close()
        print(f"❌ Checkout Transaction Error: {e}")
        flash("Checkout failed. Please try again.", "error")
        return redirect(url_for("view_cart"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")), debug=True)