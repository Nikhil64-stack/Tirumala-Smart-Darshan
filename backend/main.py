from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import sqlite3
import uuid
from datetime import datetime, timedelta

from backend.database import get_db_connection, hash_password
from backend.schemas import (
    UserRegister,
    UserLogin,
    BookingCreate,
    QueueUpdate,
    TokenUpdate,
    ExitPassVerify,
    SsdQuotaRelease
)


# ============================================================
# APP
# ============================================================

app = FastAPI(
    title="Tirumala Smart Darshan API",
    description="Smart Pilgrim Queue Management System SWE API",
    version="1.0.0"
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,

    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000"
    ],

    allow_credentials=True,

    allow_methods=["*"],

    allow_headers=["*"]
)


# ============================================================
# HOME
# ============================================================

@app.get("/")
def home():

    return {
        "message": "Tirumala Smart Darshan API",
        "status": "running"
    }


# ============================================================
# SWE ENDPOINTS
# ============================================================

# Helpers for JSON or row conversion
def dict_from_row(row):
    return dict(row) if row else None

# Helper to create notification
def create_notification_helper(conn, user_id: int, message: str, notif_type: str = "Info"):
    cursor = conn.cursor()
    now_str = datetime.now().isoformat()
    cursor.execute(
        "INSERT INTO notifications (user_id, message, type, read, timestamp) VALUES (?, ?, ?, 0, ?)",
        (user_id, message, notif_type, now_str)
    )

# --- AUTHENTICATION ---

@app.post("/api/auth/register")
def register_user(req: UserRegister):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed = hash_password(req.password)
    try:
        cursor.execute(
            "INSERT INTO users (name, email, password, role) VALUES (?, ?, ?, ?)",
            (req.name, req.email, hashed, req.role)
        )
        conn.commit()
        user_id = cursor.lastrowid
        
        # Create welcome notification
        create_notification_helper(
            conn, 
            user_id, 
            f"Welcome to Tirumala Smart Darshan, {req.name}! Your account has been created successfully.",
            "Success"
        )
        conn.commit()
        
        return {"id": user_id, "name": req.name, "email": req.email, "role": req.role}
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Email is already registered")
    finally:
        conn.close()

@app.post("/api/auth/login")
def login_user(req: UserLogin):
    conn = get_db_connection()
    cursor = conn.cursor()
    hashed = hash_password(req.password)
    cursor.execute(
        "SELECT id, name, email, role FROM users WHERE email = ? AND password = ?",
        (req.email, hashed)
    )
    user = cursor.fetchone()
    conn.close()
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    return dict_from_row(user)


# --- DARSHAN TYPES ---

@app.get("/api/darshan/types")
def get_darshan_types():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM darshan_types")
    types = cursor.fetchall()
    conn.close()
    return [dict_from_row(t) for t in types]


# --- DARSHAN BOOKINGS ---

@app.post("/api/darshan/book")
def create_booking(req: BookingCreate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if user exists
        cursor.execute("SELECT name FROM users WHERE id = ?", (req.user_id,))
        user = cursor.fetchone()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        # Generate Booking ID
        booking_id = f"SPQ-{uuid.uuid4().hex[:6].upper()}"
        
        # Insert Booking
        cursor.execute(
            "INSERT INTO bookings (booking_id, user_id, darshan_type, date, slot, status, pilgrims_count, pilgrim_details) VALUES (?, ?, ?, ?, ?, 'Approved', ?, ?)",
            (booking_id, req.user_id, req.darshan_type, req.date, req.slot, req.pilgrims_count, req.pilgrim_details)
        )
        
        # Automatically generate default Queue position & count for this booking (Rule-based)
        import random
        queue_pos = random.randint(30, 250)
        queue_cnt = random.randint(300, 950)
        
        # Predefined thresholds for queue status:
        if queue_cnt <= 150:
            queue_level = "LOW"
        elif queue_cnt <= 400:
            queue_level = "MODERATE"
        elif queue_cnt <= 700:
            queue_level = "HIGH"
        else:
            queue_level = "VERY HIGH"
            
        processing_rate = 60 # pilgrims per hour
        people_ahead = queue_pos
        people_processed_per_hour = processing_rate
        waiting_time_hours = people_ahead / people_processed_per_hour
        waiting_time_minutes = int(waiting_time_hours * 60)
        
        cursor.execute(
            "INSERT INTO queue_status (booking_id, queue_position, queue_count, queue_status, waiting_time, people_processed_per_hour) VALUES (?, ?, ?, ?, ?, ?)",
            (booking_id, queue_pos, queue_cnt, queue_level, waiting_time_minutes, processing_rate)
        )
        
        # Generate SSD Token if there is daily quota available for that date
        has_ssd_allocated = False
        token_number_allocated = None
        if "Sarva" in req.darshan_type or "Special" in req.darshan_type:
            cursor.execute(
                "SELECT quota_id, tokens_issued, tokens_remaining FROM ssd_daily_quotas WHERE date = ? AND status = 'ACTIVE'",
                (req.date,)
            )
            quota = cursor.fetchone()
            if quota and quota["tokens_remaining"] > 0:
                quota_id = quota["quota_id"]
                token_id = f"SSD-{uuid.uuid4().hex[:6].upper()}"
                token_number_allocated = 45000 + quota["tokens_issued"] + 1
                cursor.execute(
                    "INSERT INTO ssd_tokens (token_id, quota_id, booking_id, user_id, token_number, status) VALUES (?, ?, ?, ?, ?, 'ALLOCATED')",
                    (token_id, quota_id, booking_id, req.user_id, token_number_allocated)
                )
                cursor.execute(
                    "UPDATE ssd_daily_quotas SET tokens_issued = tokens_issued + 1, tokens_remaining = tokens_remaining - 1 WHERE quota_id = ?",
                    (quota_id,)
                )
                has_ssd_allocated = True
            
        # Add Notification
        notif_msg = f"Your booking ({booking_id}) for {req.darshan_type} on {req.date} at {req.slot} has been successfully approved."
        if has_ssd_allocated:
            notif_msg += f" SSD Token #{token_number_allocated} has been allocated."
        create_notification_helper(
            conn,
            req.user_id,
            notif_msg,
            "Success"
        )
        
        conn.commit()
        return {
            "booking_id": booking_id,
            "darshan_type": req.darshan_type,
            "date": req.date,
            "slot": req.slot,
            "status": "Approved"
        }
    except Exception as e:
        conn.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/darshan/bookings/{user_id}")
def get_user_bookings(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.*, q.queue_position, q.queue_count, q.queue_status, q.waiting_time,
               t.token_number, t.status as token_status,
               p.pass_id, p.status as pass_status
        FROM bookings b
        LEFT JOIN queue_status q ON b.booking_id = q.booking_id
        LEFT JOIN ssd_tokens t ON b.booking_id = t.booking_id
        LEFT JOIN qr_exit_passes p ON b.booking_id = p.booking_id
        WHERE b.user_id = ?
        ORDER BY b.rowid DESC
    """, (user_id,))
    bookings = cursor.fetchall()
    conn.close()
    return [dict_from_row(b) for b in bookings]


# --- QUEUE MANAGEMENT ---

@app.get("/api/queue/status/{booking_id}")
def get_queue_status(booking_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM queue_status WHERE booking_id = ?", (booking_id,))
    q = cursor.fetchone()
    conn.close()
    if not q:
        raise HTTPException(status_code=404, detail="Queue status for booking not found")
    return dict_from_row(q)

@app.post("/api/admin/queue/update")
def update_queue(req: QueueUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if booking exists
        cursor.execute("SELECT user_id FROM bookings WHERE booking_id = ?", (req.booking_id,))
        booking = cursor.fetchone()
        if not booking:
            raise HTTPException(status_code=404, detail="Booking ID not found")
        
        user_id = booking["user_id"]
        
        # Calculate waiting time using explicit variable names:
        people_ahead = req.queue_position
        people_processed_per_hour = req.people_processed_per_hour if req.people_processed_per_hour > 0 else 60
        waiting_time_hours = people_ahead / people_processed_per_hour
        waiting_time_minutes = int(waiting_time_hours * 60)
        
        normalized_status = req.queue_status.upper() if req.queue_status else "MODERATE"
        
        cursor.execute("""
            UPDATE queue_status 
            SET queue_position = ?, queue_count = ?, queue_status = ?, waiting_time = ?, people_processed_per_hour = ?
            WHERE booking_id = ?
        """, (req.queue_position, req.queue_count, normalized_status, waiting_time_minutes, people_processed_per_hour, req.booking_id))
        
        # Add Notification to user about queue update
        create_notification_helper(
            conn,
            user_id,
            f"Your Queue position for booking {req.booking_id} has been updated to #{req.queue_position} by temple authority. Estimated wait time: {waiting_time_minutes} minutes.",
            "Warning"
        )
        
        conn.commit()
        return {"status": "success", "message": "Queue status updated successfully", "waiting_time": waiting_time_minutes}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/admin/queue/status")
def get_all_queues():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.booking_id, b.darshan_type, b.date, b.slot, u.name as user_name,
               q.queue_position, q.queue_count, q.queue_status, q.waiting_time, q.people_processed_per_hour
        FROM bookings b
        JOIN users u ON b.user_id = u.id
        LEFT JOIN queue_status q ON b.booking_id = q.booking_id
    """)
    queues = cursor.fetchall()
    conn.close()
    return [dict_from_row(q) for q in queues]


# --- QR EXIT PASS ---

@app.post("/api/qr/exit-pass/create")
def create_exit_pass(req: dict):
    booking_id = req.get("booking_id")
    user_id = req.get("user_id")
    if not booking_id or not user_id:
        raise HTTPException(status_code=400, detail="booking_id and user_id are required")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if pass already exists for this booking
        cursor.execute("SELECT pass_id FROM qr_exit_passes WHERE booking_id = ?", (booking_id,))
        existing = cursor.fetchone()
        if existing:
            return {"pass_id": existing["pass_id"], "status": "exists"}

        pass_id = f"PASS-{uuid.uuid4().hex[:6].upper()}"
        issue_time = datetime.now().isoformat()
        expiry_time = (datetime.now() + timedelta(hours=3)).isoformat()
        
        cursor.execute(
            "INSERT INTO qr_exit_passes (pass_id, booking_id, user_id, issue_time, expiry_time, status) VALUES (?, ?, ?, ?, ?, 'Active')",
            (pass_id, booking_id, user_id, issue_time, expiry_time)
        )
        
        create_notification_helper(
            conn,
            user_id,
            f"Temporary Exit Pass {pass_id} generated. It is valid for 3 hours until {datetime.now() + timedelta(hours=3):%H:%M}.",
            "Info"
        )
        conn.commit()
        return {
            "pass_id": pass_id,
            "booking_id": booking_id,
            "user_id": user_id,
            "issue_time": issue_time,
            "expiry_time": expiry_time,
            "status": "Active"
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/qr/exit-pass/{pass_id}")
def get_exit_pass(pass_id: str):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.*, u.name as user_name, b.darshan_type 
        FROM qr_exit_passes p
        JOIN users u ON p.user_id = u.id
        JOIN bookings b ON p.booking_id = b.booking_id
        WHERE p.pass_id = ?
    """, (pass_id,))
    pass_row = cursor.fetchone()
    conn.close()
    if not pass_row:
        raise HTTPException(status_code=404, detail="Exit pass not found")
    return dict_from_row(pass_row)

@app.post("/api/qr/exit-pass/verify")
def verify_exit_pass(req: ExitPassVerify):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT * FROM qr_exit_passes WHERE pass_id = ?", (req.pass_id,))
        pass_row = cursor.fetchone()
        if not pass_row:
            return {"valid": False, "message": "Exit pass does not exist"}
        
        user_id = pass_row["user_id"]
        booking_id = pass_row["booking_id"]
        status = pass_row["status"]
        expiry_time_str = pass_row["expiry_time"]
        expiry_time = datetime.fromisoformat(expiry_time_str)
        
        if status == "Used":
            return {"valid": False, "message": "Exit Pass has already been used"}
        if status == "Expired" or datetime.now() > expiry_time:
            if status != "Expired":
                cursor.execute("UPDATE qr_exit_passes SET status = 'Expired' WHERE pass_id = ?", (req.pass_id,))
                create_notification_helper(
                    conn,
                    user_id,
                    f"Your exit pass {req.pass_id} has expired (expired on {expiry_time_str}). Please contact gate staff for re-entry validation.",
                    "Warning"
                )
                conn.commit()
            return {"valid": False, "message": "Exit Pass has expired"}
        if status != "Active":
            return {"valid": False, "message": f"Exit Pass status is {status}"}
            
        # Update pass status to used (indicating pilgrim re-entered)
        cursor.execute("UPDATE qr_exit_passes SET status = 'Used' WHERE pass_id = ?", (req.pass_id,))
        
        # Notify user
        create_notification_helper(
            conn,
            user_id,
            f"Your exit pass {req.pass_id} has been verified at the entry gate. Welcome back to the main queue.",
            "Success"
        )
        conn.commit()
        return {
            "valid": True, 
            "message": "Valid Exit Pass. Re-entry approved.",
            "details": {
                "pass_id": req.pass_id,
                "booking_id": booking_id,
                "user_id": user_id
            }
        }
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# --- SSD DAILY QUOTAS ---

@app.post("/api/admin/ssd/quota/release")
def release_ssd_quota(req: SsdQuotaRelease):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if quota already exists for this date
        cursor.execute("SELECT * FROM ssd_daily_quotas WHERE date = ?", (req.date,))
        existing = cursor.fetchone()
        if existing:
            raise HTTPException(status_code=400, detail=f"SSD Token Quota already exists for {req.date}.")
        
        quota_id = f"QTA-{uuid.uuid4().hex[:6].upper()}"
        cursor.execute(
            "INSERT INTO ssd_daily_quotas (quota_id, date, total_released, tokens_issued, tokens_remaining, tokens_used, status) VALUES (?, ?, ?, 0, ?, 0, 'ACTIVE')",
            (quota_id, req.date, req.total_released, req.total_released)
        )
        conn.commit()
        return {"status": "success", "quota_id": quota_id, "date": req.date, "total_released": req.total_released}
    except Exception as e:
        conn.rollback()
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()

@app.get("/api/admin/ssd/quotas")
def get_ssd_quotas():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM ssd_daily_quotas ORDER BY date DESC")
    quotas = cursor.fetchall()
    conn.close()
    return [dict_from_row(q) for q in quotas]


# --- SSD TOKENS ---

@app.get("/api/ssd/tokens")
def get_ssd_tokens():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.*, b.darshan_type, b.date, u.name as user_name 
        FROM ssd_tokens t
        LEFT JOIN bookings b ON t.booking_id = b.booking_id
        LEFT JOIN users u ON b.user_id = u.id
    """)
    tokens = cursor.fetchall()
    conn.close()
    return [dict_from_row(t) for t in tokens]

@app.post("/api/ssd/token/update")
def update_ssd_token(req: TokenUpdate):
    conn = get_db_connection()
    cursor = conn.cursor()
    try:
        # Check if token exists
        cursor.execute("SELECT * FROM ssd_tokens WHERE token_id = ?", (req.token_id,))
        token = cursor.fetchone()
        if not token:
            # If token does not exist, let's create a new token number
            import random
            t_num = random.randint(10000, 99999)
            cursor.execute(
                "INSERT INTO ssd_tokens (token_id, booking_id, token_number, status) VALUES (?, ?, ?, ?)",
                (req.token_id, req.booking_id, t_num, req.status)
            )
        else:
            cursor.execute(
                "UPDATE ssd_tokens SET booking_id = ?, status = ? WHERE token_id = ?",
                (req.booking_id, req.status, req.token_id)
            )
            
        # Notify user if allocated/updated
        if req.booking_id:
            cursor.execute("SELECT user_id FROM bookings WHERE booking_id = ?", (req.booking_id,))
            booking = cursor.fetchone()
            if booking:
                create_notification_helper(
                    conn,
                    booking["user_id"],
                    f"Your SSD token status for booking {req.booking_id} has been updated to: {req.status}.",
                    "Info"
                )
                
        conn.commit()
        return {"status": "success", "message": "SSD Token updated successfully"}
    except Exception as e:
        conn.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        conn.close()


# --- NOTIFICATIONS ---

@app.get("/api/notifications/{user_id}")
def get_user_notifications(user_id: int):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT * FROM notifications WHERE user_id = ? ORDER BY timestamp DESC",
        (user_id,)
    )
    notifs = cursor.fetchall()
    conn.close()
    return [dict_from_row(n) for n in notifs]

@app.post("/api/notifications/read")
def read_notifications(req: dict):
    user_id = req.get("user_id")
    if not user_id:
        raise HTTPException(status_code=400, detail="user_id is required")
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE notifications SET read = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return {"status": "success"}