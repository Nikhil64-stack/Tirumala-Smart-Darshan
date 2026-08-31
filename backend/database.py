import os
import sqlite3
import hashlib
import json
from datetime import datetime, timedelta

DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "darshan_system.db"
)

def hash_password(password: str) -> str:
    """Computes SHA-256 hash of a password."""
    return hashlib.sha256(password.encode("utf-8")).hexdigest()

def get_db_connection():
    """Returns a connection to the SQLite database with row factory enabled."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes database tables and seeds initial data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # Create Users Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT NOT NULL CHECK(role IN ('user', 'admin', 'staff'))
    );
    """)

    # Create Darshan Types Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS darshan_types (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        description TEXT NOT NULL,
        availability INTEGER DEFAULT 1
    );
    """)

    # Create Bookings Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        booking_id TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL,
        darshan_type TEXT NOT NULL,
        date TEXT NOT NULL,
        slot TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Approved',
        pilgrims_count INTEGER NOT NULL DEFAULT 1,
        pilgrim_details TEXT,
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Create Queue Status Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS queue_status (
        queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id TEXT NOT NULL UNIQUE,
        queue_position INTEGER NOT NULL,
        queue_count INTEGER NOT NULL,
        queue_status TEXT NOT NULL,
        waiting_time INTEGER NOT NULL,
        people_processed_per_hour INTEGER NOT NULL DEFAULT 60,
        FOREIGN KEY (booking_id) REFERENCES bookings (booking_id)
    );
    """)

    # Create QR Exit Passes Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS qr_exit_passes (
        pass_id TEXT PRIMARY KEY,
        booking_id TEXT NOT NULL,
        user_id INTEGER NOT NULL,
        issue_time TEXT NOT NULL,
        expiry_time TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'Active',
        FOREIGN KEY (booking_id) REFERENCES bookings (booking_id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Create SSD Daily Quotas Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ssd_daily_quotas (
        quota_id TEXT PRIMARY KEY,
        date TEXT UNIQUE NOT NULL,
        total_released INTEGER NOT NULL,
        tokens_issued INTEGER DEFAULT 0,
        tokens_remaining INTEGER NOT NULL,
        tokens_used INTEGER DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'ACTIVE'
    );
    """)

    # Create SSD Tokens Table
    cursor.execute("PRAGMA table_info(ssd_tokens)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "quota_id" not in columns:
        cursor.execute("DROP TABLE IF EXISTS ssd_tokens")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ssd_tokens (
        token_id TEXT PRIMARY KEY,
        quota_id TEXT,
        booking_id TEXT UNIQUE,
        user_id INTEGER,
        token_number INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'ALLOCATED',
        FOREIGN KEY (quota_id) REFERENCES ssd_daily_quotas (quota_id),
        FOREIGN KEY (booking_id) REFERENCES bookings (booking_id),
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Create Notifications Table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        message TEXT NOT NULL,
        type TEXT NOT NULL,
        read INTEGER DEFAULT 0,
        timestamp TEXT NOT NULL,
        FOREIGN KEY (user_id) REFERENCES users (id)
    );
    """)

    # Ensure queue_status has people_processed_per_hour
    cursor.execute("PRAGMA table_info(queue_status)")
    columns = [row["name"] for row in cursor.fetchall()]
    if "people_processed_per_hour" not in columns:
        cursor.execute("ALTER TABLE queue_status ADD COLUMN people_processed_per_hour INTEGER NOT NULL DEFAULT 60")

    conn.commit()

    # ----------------------------------------------------
    # Seed Initial Data
    # ----------------------------------------------------
    
    # 1. Seed Roles/Users
    default_users = [
        ("TTD Admin", "admin@ttd.org", hash_password("admin123"), "admin"),
        ("Temple Gate Guard", "staff@ttd.org", hash_password("staff123"), "staff"),
        ("Nikhil", "pilgrim@gmail.com", hash_password("pilgrim123"), "user")
    ]
    for name, email, pwd, role in default_users:
        try:
            cursor.execute(
                "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
                (name, email, pwd, role)
            )
        except sqlite3.IntegrityError:
            pass

    # 2. Seed Darshan Types
    darshan_types = [
        ("Sarva Darshan (Free)", "Free general queue booking for all pilgrims. Expected waiting is high during weekends.", 1),
        ("Special Entry Darshan (Rs 300)", "Rs 300 paid entry offering a quicker entry channel with medium waiting times.", 1),
        ("VIP Darshan", "Privileged pass entry with minimal waiting compartments. Requires reference letters or special protocols.", 1),
        ("Senior Citizen Darshan", "Dedicated queue slot for pilgrims above 60 years or with physical challenges. Highly subsidized waiting times.", 1),
        ("Infant Entry", "Free entry for infants under 1 year and their parents. Minimal waiting.", 1),
        ("Seva Darshan", "Special ticketed entry for morning/evening rituals (Arjitha Sevas) inside the sanctum.", 1)
    ]
    for d_name, desc, avail in darshan_types:
        try:
            cursor.execute(
                "INSERT INTO darshan_types (name, description, availability) VALUES (?, ?, ?)",
                (d_name, desc, avail)
            )
        except sqlite3.IntegrityError:
            pass

    conn.commit()
    conn.close()
    print("Database initialized and default values seeded successfully.")

if __name__ == "__main__":
    init_db()
