
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash
from database import get_connection, create_tables
from functools import wraps

app = Flask(__name__)
app.secret_key = "freshroute_change_this_secret_key"

create_tables()


# =====================================
# LOGIN AND ROLE SECURITY
# =====================================

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please login first.")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def role_required(role):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                flash("Please login first.")
                return redirect(url_for("login"))

            if session.get("role") != role:
                flash("Access denied.")
                return redirect(url_for("home"))

            return f(*args, **kwargs)
        return decorated
    return decorator


# =====================================
# HOME
# =====================================

@app.route("/")
def home():
    conn = get_connection()

    products = conn.execute("""
        SELECT products.*, users.name AS farmer_name
        FROM products
        JOIN users ON products.farmer_id = users.id
        WHERE products.quantity > 0
        ORDER BY products.id DESC
        LIMIT 6
    """).fetchall()

    conn.close()
    return render_template("index.html", products=products)


# =====================================
# REGISTER
# =====================================

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":

        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        role = request.form.get("role", "")

        if not name or not email or len(password) < 8:
            flash("Password must be at least 8 characters.")
            return redirect(url_for("register"))

        if role not in ("farmer", "buyer"):
            flash("Invalid account type.")
            return redirect(url_for("register"))

        conn = get_connection()

        try:
            conn.execute("""
                INSERT INTO users (name, email, password, role)
                VALUES (?, ?, ?, ?)
            """, (
                name, email,
                generate_password_hash(password),
                role
            ))
            conn.commit()
            flash("Registration successful. Please login.")
            return redirect(url_for("login"))

        except Exception:
            flash("Email already registered.")

        finally:
            conn.close()

    return render_template("register.html")


# =====================================
# LOGIN
# =====================================

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        conn = get_connection()
        user = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email,)
        ).fetchone()
        conn.close()

        if user and check_password_hash(user["password"], password):

            session.clear()
            session["user_id"] = user["id"]
            session["name"] = user["name"]
            session["role"] = user["role"]

            if user["role"] == "admin":
                return redirect(url_for("admin"))

            if user["role"] == "farmer":
                return redirect(url_for("farmer"))

            return redirect(url_for("marketplace"))

        flash("Invalid email or password.")

    return render_template("login.html")


# =====================================
# LOGOUT
# =====================================

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


# =====================================
# MARKETPLACE
# =====================================

@app.route("/marketplace")
def marketplace():
    conn = get_connection()

    products = conn.execute("""
        SELECT products.*, users.name AS farmer_name
        FROM products
        JOIN users ON products.farmer_id = users.id
        WHERE products.quantity > 0
        ORDER BY products.id DESC
    """).fetchall()

    conn.close()

    return render_template("marketplace.html", products=products)


# =====================================
# FARMER DASHBOARD
# =====================================

@app.route("/farmer")
@login_required
@role_required("farmer")
def farmer():
    conn = get_connection()

    products = conn.execute("""
        SELECT *
        FROM products
        WHERE farmer_id = ?
        ORDER BY id DESC
    """, (session["user_id"],)).fetchall()

    conn.close()

    return render_template("farmer.html", products=products)


# =====================================
# ADD PRODUCT
# =====================================

@app.route("/add-product", methods=["POST"])
@login_required
@role_required("farmer")
def add_product():

    name = request.form.get("name", "").strip()
    category = request.form.get("category", "").strip()

    try:
        price = float(request.form.get("price", 0))
        quantity = int(request.form.get("quantity", 0))
    except (ValueError, TypeError):
        flash("Invalid price or quantity.")
        return redirect(url_for("farmer"))

    if not name or price <= 0 or quantity <= 0:
        flash("Enter valid product details.")
        return redirect(url_for("farmer"))

    conn = get_connection()

    conn.execute("""
        INSERT INTO products
        (farmer_id, name, price, quantity, category)
        VALUES (?, ?, ?, ?, ?)
    """, (
        session["user_id"],
        name,
        price,
        quantity,
        category
    ))

    conn.commit()
    conn.close()

    flash("Product added successfully!")
    return redirect(url_for("farmer"))


# =====================================
# DELETE PRODUCT
# =====================================

@app.route("/delete-product/<int:product_id>", methods=["POST"])
@login_required
@role_required("farmer")
def delete_product(product_id):

    conn = get_connection()

    conn.execute("""
        DELETE FROM products
        WHERE id = ? AND farmer_id = ?
    """, (product_id, session["user_id"]))

    conn.commit()
    conn.close()

    flash("Product deleted.")
    return redirect(url_for("farmer"))


# =====================================
# BUY PRODUCT
# =====================================

@app.route("/buy/<int:product_id>", methods=["POST"])
@login_required
@role_required("buyer")
def buy(product_id):

    try:
        quantity = int(request.form.get("quantity", 1))
    except (ValueError, TypeError):
        flash("Invalid quantity.")
        return redirect(url_for("marketplace"))

    if quantity <= 0:
        flash("Quantity must be positive.")
        return redirect(url_for("marketplace"))

    conn = get_connection()

    try:
        conn.execute("BEGIN IMMEDIATE")

        product = conn.execute("""
            SELECT *
            FROM products
            WHERE id = ?
        """, (product_id,)).fetchone()

        if not product or product["quantity"] < quantity:
            conn.rollback()
            flash("Product unavailable or insufficient stock.")
            return redirect(url_for("marketplace"))

        total_price = product["price"] * quantity

        conn.execute("""
            INSERT INTO orders
            (buyer_id, product_id, quantity, total_price)
            VALUES (?, ?, ?, ?)
        """, (
            session["user_id"],
            product_id,
            quantity,
            total_price
        ))

        conn.execute("""
            UPDATE products
            SET quantity = quantity - ?
            WHERE id = ?
        """, (quantity, product_id))

        conn.commit()
        flash("Order placed successfully!")

    except Exception:
        conn.rollback()
        flash("Could not place order.")

    finally:
        conn.close()

    return redirect(url_for("marketplace"))


# =====================================
# MY ORDERS
# =====================================

@app.route("/my-orders")
@login_required
def my_orders():

    conn = get_connection()

    query = """
        SELECT orders.*,
               products.name AS product_name,
               buyer.name AS buyer_name,
               farmer.name AS farmer_name
        FROM orders
        JOIN products ON orders.product_id = products.id
        JOIN users AS buyer ON orders.buyer_id = buyer.id
        JOIN users AS farmer ON products.farmer_id = farmer.id
    """

    if session["role"] == "buyer":
        orders = conn.execute(
            query + " WHERE orders.buyer_id = ? ORDER BY orders.id DESC",
            (session["user_id"],)
        ).fetchall()

    elif session["role"] == "farmer":
        orders = conn.execute(
            query + " WHERE products.farmer_id = ? ORDER BY orders.id DESC",
            (session["user_id"],)
        ).fetchall()

    else:
        orders = conn.execute(
            query + " ORDER BY orders.id DESC"
        ).fetchall()

    conn.close()

    return render_template("orders.html", orders=orders)


# =====================================
# UPDATE ORDER STATUS (NEW FEATURE)
# =====================================

@app.route("/update-order-status/<int:order_id>", methods=["POST"])
@login_required
@role_required("farmer")
def update_order_status(order_id):

    new_status = request.form.get("status", "")

    conn = get_connection()

    order = conn.execute("""
        SELECT orders.status
        FROM orders
        JOIN products ON orders.product_id = products.id
        WHERE orders.id = ?
        AND products.farmer_id = ?
    """, (order_id, session["user_id"])).fetchone()

    if not order:
        conn.close()
        flash("Order not found or access denied.")
        return redirect(url_for("my_orders"))

    allowed_transitions = {
        "Pending": ["Confirmed", "Cancelled"],
        "Confirmed": ["Completed", "Cancelled"],
        "Completed": [],
        "Cancelled": []
    }

    current_status = order["status"]

    if new_status not in allowed_transitions.get(current_status, []):
        conn.close()
        flash("Invalid order status change.")
        return redirect(url_for("my_orders"))

    conn.execute("""
        UPDATE orders
        SET status = ?
        WHERE id = ?
    """, (new_status, order_id))

    conn.commit()
    conn.close()

    flash("Order status updated to " + new_status + "!")
    return redirect(url_for("my_orders"))


# =====================================
# ADMIN DASHBOARD
# =====================================

@app.route("/admin")
@login_required
@role_required("admin")
def admin():

    conn = get_connection()

    users = conn.execute("""
        SELECT id, name, email, role
        FROM users ORDER BY id DESC
    """).fetchall()

    products = conn.execute("""
        SELECT * FROM products ORDER BY id DESC
    """).fetchall()

    orders = conn.execute("""
        SELECT orders.*, products.name AS product_name
        FROM orders
        JOIN products ON orders.product_id = products.id
        ORDER BY orders.id DESC
    """).fetchall()

    conn.close()

    return render_template(
        "admin.html",
        users=users,
        products=products,
        orders=orders
    )


# =====================================
# CREATE ACCOUNT FROM ADMIN
# =====================================

@app.route("/admin/create", methods=["POST"])
@login_required
@role_required("admin")
def create_admin():

    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip().lower()
    password = request.form.get("password", "")
    role = request.form.get("role", "")

    if not name or not email or len(password) < 8:
        flash("Enter valid account details.")
        return redirect(url_for("admin"))

    if role not in ("farmer", "buyer", "admin"):
        flash("Invalid role.")
        return redirect(url_for("admin"))

    conn = get_connection()

    try:
        conn.execute("""
            INSERT INTO users (name, email, password, role)
            VALUES (?, ?, ?, ?)
        """, (
            name,
            email,
            generate_password_hash(password),
            role
        ))

        conn.commit()
        flash("Account created successfully.")

    except Exception:
        flash("Email already exists.")

    finally:
        conn.close()

    return redirect(url_for("admin"))


# =====================================
# RUN APPLICATION
# =====================================

if __name__ == "__main__":
    app.run(debug=True)
