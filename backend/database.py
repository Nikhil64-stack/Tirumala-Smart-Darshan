import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "darshan_system.db")

def get_db_connection():
    """Establishes and returns a database connection with dict-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    """Initializes SQLite database tables and seeds initial data."""
    conn = get_db_connection()
    cursor = conn.cursor()

    # 1. USERS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS USERS (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT UNIQUE NOT NULL,
        phone TEXT NOT NULL,
        password TEXT NOT NULL,
        age INTEGER,
        gender TEXT,
        address TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 2. ADMINS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS ADMINS (
        admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        role TEXT DEFAULT 'Admin',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 3. STAFF table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS STAFF (
        staff_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        email TEXT UNIQUE NOT NULL,
        password TEXT NOT NULL,
        badge_number TEXT UNIQUE NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 4. SESSIONS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS SESSIONS (
        session_token TEXT PRIMARY KEY,
        user_id INTEGER,
        admin_id INTEGER,
        staff_id INTEGER,
        role TEXT NOT NULL DEFAULT 'User',
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES USERS(user_id) ON DELETE CASCADE,
        FOREIGN KEY (admin_id) REFERENCES ADMINS(admin_id) ON DELETE CASCADE,
        FOREIGN KEY (staff_id) REFERENCES STAFF(staff_id) ON DELETE CASCADE
    );
    """)

    # 5. DARSHAN table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS DARSHAN (
        darshan_id INTEGER PRIMARY KEY AUTOINCREMENT,
        darshan_name TEXT UNIQUE NOT NULL,
        description TEXT,
        price REAL DEFAULT 0,
        is_bookable INTEGER DEFAULT 1,
        availability_status TEXT NOT NULL
    );
    """)

    # 6. BOOKINGS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS BOOKINGS (
        booking_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        darshan_id INTEGER NOT NULL,
        booking_date TEXT NOT NULL,
        time_slot TEXT NOT NULL,
        number_of_persons INTEGER DEFAULT 1,
        total_amount REAL DEFAULT 0,
        payment_status TEXT DEFAULT 'Successful',
        status TEXT NOT NULL,
        queue_position INTEGER NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES USERS(user_id) ON DELETE CASCADE,
        FOREIGN KEY (darshan_id) REFERENCES DARSHAN(darshan_id) ON DELETE CASCADE
    );
    """)

    # 7. BOOKING_PILGRIMS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS BOOKING_PILGRIMS (
        pilgrim_id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        age INTEGER NOT NULL,
        gender TEXT NOT NULL,
        FOREIGN KEY (booking_id) REFERENCES BOOKINGS(booking_id) ON DELETE CASCADE
    );
    """)

    # 8. QUEUE table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS QUEUE (
        queue_id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER UNIQUE NOT NULL,
        position INTEGER NOT NULL,
        status TEXT NOT NULL,
        estimated_waiting_time INTEGER NOT NULL,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (booking_id) REFERENCES BOOKINGS(booking_id) ON DELETE CASCADE
    );
    """)

    # 9. QUEUE_SETTINGS table (for deterministic wait time calculation)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS QUEUE_SETTINGS (
        setting_id INTEGER PRIMARY KEY AUTOINCREMENT,
        avg_processing_mins REAL DEFAULT 2.0,
        active_counters INTEGER DEFAULT 10,
        queue_congestion_level TEXT DEFAULT 'MEDIUM',
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 10. SSD_QUOTA table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS SSD_QUOTA (
        quota_id INTEGER PRIMARY KEY AUTOINCREMENT,
        date TEXT UNIQUE NOT NULL,
        total_quota INTEGER NOT NULL,
        used_quota INTEGER DEFAULT 0,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # 11. QR_EXIT_PASS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS QR_EXIT_PASS (
        qr_id INTEGER PRIMARY KEY AUTOINCREMENT,
        booking_id INTEGER NOT NULL,
        qr_data TEXT UNIQUE NOT NULL,
        reason TEXT,
        expected_return_time TEXT,
        status TEXT NOT NULL,
        generated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expiry_time TIMESTAMP NOT NULL,
        verified_by TEXT,
        verified_at TIMESTAMP,
        FOREIGN KEY (booking_id) REFERENCES BOOKINGS(booking_id) ON DELETE CASCADE
    );
    """)

    # 12. NOTIFICATIONS table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS NOTIFICATIONS (
        notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        type TEXT DEFAULT 'info',
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES USERS(user_id) ON DELETE CASCADE
    );
    """)

    conn.commit()

    # Upgrade existing SESSIONS table if user_id has NOT NULL constraint
    cursor.execute("PRAGMA table_info(SESSIONS);")
    s_cols_info = cursor.fetchall()
    user_id_notnull = any(row[1] == 'user_id' and row[3] == 1 for row in s_cols_info)
    if user_id_notnull:
        cursor.execute("DROP TABLE SESSIONS;")
        cursor.execute("""
        CREATE TABLE SESSIONS (
            session_token TEXT PRIMARY KEY,
            user_id INTEGER,
            admin_id INTEGER,
            staff_id INTEGER,
            role TEXT NOT NULL DEFAULT 'User',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES USERS(user_id) ON DELETE CASCADE,
            FOREIGN KEY (admin_id) REFERENCES ADMINS(admin_id) ON DELETE CASCADE,
            FOREIGN KEY (staff_id) REFERENCES STAFF(staff_id) ON DELETE CASCADE
        );
        """)

    # Upgrade existing SESSIONS table if missing admin_id, staff_id, role
    cursor.execute("PRAGMA table_info(SESSIONS);")
    s_cols = [row[1] for row in cursor.fetchall()]
    if "admin_id" not in s_cols:
        cursor.execute("ALTER TABLE SESSIONS ADD COLUMN admin_id INTEGER;")
    if "staff_id" not in s_cols:
        cursor.execute("ALTER TABLE SESSIONS ADD COLUMN staff_id INTEGER;")
    if "role" not in s_cols:
        cursor.execute("ALTER TABLE SESSIONS ADD COLUMN role TEXT DEFAULT 'User';")

    # Upgrade existing DARSHAN table if missing price/is_bookable columns
    cursor.execute("PRAGMA table_info(DARSHAN);")
    cols = [row[1] for row in cursor.fetchall()]
    if "price" not in cols:
        cursor.execute("ALTER TABLE DARSHAN ADD COLUMN price REAL DEFAULT 0;")
    if "is_bookable" not in cols:
        cursor.execute("ALTER TABLE DARSHAN ADD COLUMN is_bookable INTEGER DEFAULT 1;")

    # Upgrade existing USERS table if missing age, gender, address
    cursor.execute("PRAGMA table_info(USERS);")
    user_cols = [row[1] for row in cursor.fetchall()]
    if "age" not in user_cols:
        cursor.execute("ALTER TABLE USERS ADD COLUMN age INTEGER;")
    if "gender" not in user_cols:
        cursor.execute("ALTER TABLE USERS ADD COLUMN gender TEXT;")
    if "address" not in user_cols:
        cursor.execute("ALTER TABLE USERS ADD COLUMN address TEXT;")

    # Upgrade existing QR_EXIT_PASS table if missing columns
    cursor.execute("PRAGMA table_info(QR_EXIT_PASS);")
    qr_cols = [row[1] for row in cursor.fetchall()]
    if "reason" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN reason TEXT;")
    if "expected_return_time" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN expected_return_time TEXT;")
    if "verified_by" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN verified_by TEXT;")
    if "verified_at" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN verified_at TIMESTAMP;")
    if "requested_return_time" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN requested_return_time TEXT;")
    if "assigned_return_time" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN assigned_return_time TIMESTAMP;")
    if "staff_notes" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN staff_notes TEXT;")
    if "approved_by" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN approved_by TEXT;")
    if "approved_at" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN approved_at TIMESTAMP;")
    if "rejected_by" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN rejected_by TEXT;")
    if "rejected_at" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN rejected_at TIMESTAMP;")
    if "rejection_reason" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN rejection_reason TEXT;")
    if "reminder_sent" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN reminder_sent INTEGER DEFAULT 0;")
    if "reminder_time" not in qr_cols:
        cursor.execute("ALTER TABLE QR_EXIT_PASS ADD COLUMN reminder_time TIMESTAMP;")

    # Upgrade BOOKINGS table if missing number_of_persons, total_amount, payment_status
    cursor.execute("PRAGMA table_info(BOOKINGS);")
    b_cols = [row[1] for row in cursor.fetchall()]
    if "number_of_persons" not in b_cols:
        cursor.execute("ALTER TABLE BOOKINGS ADD COLUMN number_of_persons INTEGER DEFAULT 1;")
    if "total_amount" not in b_cols:
        cursor.execute("ALTER TABLE BOOKINGS ADD COLUMN total_amount REAL DEFAULT 0;")
    if "payment_status" not in b_cols:
        cursor.execute("ALTER TABLE BOOKINGS ADD COLUMN payment_status TEXT DEFAULT 'Successful';")

    # Upgrade QUEUE_SETTINGS table for per-Darshan manual waiting time & active counters
    cursor.execute("PRAGMA table_info(QUEUE_SETTINGS);")
    qs_cols = [row[1] for row in cursor.fetchall()]
    if "darshan_id" not in qs_cols:
        cursor.execute("ALTER TABLE QUEUE_SETTINGS ADD COLUMN darshan_id INTEGER;")
    if "estimated_waiting_time" not in qs_cols:
        cursor.execute("ALTER TABLE QUEUE_SETTINGS ADD COLUMN estimated_waiting_time REAL;")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_queue_settings_darshan ON QUEUE_SETTINGS(darshan_id);")

    # Safe Seed DARSHAN types cleanly without deleting existing records
    darshan_types = [
        ("Special Entry Darshan (Rs. 300)", "Quick access darshan with pre-booked slot.", 300.0, 1, "Available"),
        ("Sarvadarsanam (Free Entry)", "General access darshan for all pilgrims. Direct walk-in without online booking.", 0.0, 0, "Walk-in Only"),
        ("Divya Darshan (Pedestrian)", "Darshan for pilgrims who climb footpaths to Tirumala.", 0.0, 1, "Available"),
        ("VIP Break Darshan", "Privileged darshan for VIP protocol holders.", 500.0, 1, "Available"),
        ("Senior Citizen & Special Needs Darshan", "Dedicated slot for senior citizens & physically challenged pilgrims.", 0.0, 1, "Available")
    ]
    for d_name, d_desc, d_price, d_bookable, d_status in darshan_types:
        cursor.execute("SELECT darshan_id FROM DARSHAN WHERE darshan_name = ?", (d_name,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO DARSHAN (darshan_name, description, price, is_bookable, availability_status) VALUES (?, ?, ?, ?, ?);",
                (d_name, d_desc, d_price, d_bookable, d_status)
            )

    # Initialize QUEUE_SETTINGS per Darshan type if missing
    cursor.execute("SELECT darshan_id FROM DARSHAN;")
    all_d_ids = [row[0] for row in cursor.fetchall()]
    for d_id in all_d_ids:
        cursor.execute("SELECT setting_id FROM QUEUE_SETTINGS WHERE darshan_id = ?;", (d_id,))
        if not cursor.fetchone():
            cursor.execute(
                "INSERT INTO QUEUE_SETTINGS (darshan_id, estimated_waiting_time, active_counters) VALUES (?, NULL, NULL);",
                (d_id,)
            )

    # Clean up existing future bookings in active QUEUE that were erroneously set to 'Waiting'
    cursor.execute("""
        UPDATE QUEUE SET status = 'Scheduled'
        WHERE status = 'Waiting' AND booking_id IN (
            SELECT booking_id FROM BOOKINGS WHERE booking_date > date('now', 'localtime')
        );
    """)
    conn.commit()

    # Seed Default Accounts (Admin, Staff, Pilgrim)
    from backend.auth_utils import hash_password
    
    # Default Admin
    cursor.execute("SELECT admin_id FROM ADMINS WHERE email = 'admin@tirumala.org';")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO ADMINS (username, email, password, role) VALUES (?, ?, ?, ?);",
            ("admin", "admin@tirumala.org", hash_password("admin123"), "Admin")
        )

    # Default Staff
    cursor.execute("SELECT staff_id FROM STAFF WHERE email = 'staff@tirumala.org';")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO STAFF (username, email, password, badge_number) VALUES (?, ?, ?, ?);",
            ("staff", "staff@tirumala.org", hash_password("staff123"), "BADGE-101")
        )

    # Default Pilgrim
    cursor.execute("SELECT user_id FROM USERS WHERE email = 'pilgrim@example.com';")
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO USERS (name, email, phone, password, age, gender, address) VALUES (?, ?, ?, ?, ?, ?, ?);",
            ("Ramesh Kumar", "pilgrim@example.com", "9876543210", hash_password("user123"), 35, "Male", "Tirupati, AP")
        )

    # Seed Today's SSD Quota if not present
    today_str = datetime.now().strftime("%Y-%m-%d")
    cursor.execute("SELECT quota_id FROM SSD_QUOTA WHERE date = ?;", (today_str,))
    if not cursor.fetchone():
        cursor.execute(
            "INSERT INTO SSD_QUOTA (date, total_quota, used_quota) VALUES (?, ?, ?);",
            (today_str, 5000, 1800)
        )

    conn.commit()
    conn.close()
    print("Database initialized & upgraded successfully.")

if __name__ == "__main__":
    init_db()

