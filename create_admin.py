from database import get_connection
from werkzeug.security import generate_password_hash

print("Starting admin creation...")

name = "FreshRoute Admin"
email = "admin@freshroute.com"
password = "Admin@12345"

conn = get_connection()

existing = conn.execute(
    "SELECT id FROM users WHERE role = 'admin'"
).fetchone()

if existing:
    print("An admin account already exists.")
else:
    conn.execute(
        """
        INSERT INTO users (name, email, password, role)
        VALUES (?, ?, ?, ?)
        """,
        (name, email, generate_password_hash(password), "admin")
    )
    conn.commit()
    print("Admin account created successfully!")

conn.close()
print("Admin creation process finished.")