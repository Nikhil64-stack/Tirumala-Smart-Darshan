import asyncio
import calendar
import secrets
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException, Header, Depends, Body, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.schemas import (
    UserRegisterRequest,
    UserLoginRequest,
    AdminLoginRequest,
    StaffLoginRequest,
    BookingCreateRequest,
    PilgrimDetailSchema,
    SSDQuotaReleaseRequest,
    QRGenerateRequest,
    QRVerifyRequest,
    QueueSettingsUpdateRequest,
    DarshanQueueSettingsUpdateRequest,
    ExitPassRequest,
    ExitPassApproveRequest,
    ExitPassRejectRequest,
    QueueAdmissionRequest,
    CrowdPredictionRequest,
    WaitingTimePredictionRequest
)

from backend.ml_service import (
    predict_crowd,
    predict_waiting_time
)

from backend.database import get_db_connection, init_db
from backend.auth_utils import hash_password, verify_password, generate_session_token

# ============================================================
# APP INITIALIZATION
# ============================================================

app = FastAPI(
    title="Tirumala Smart Pilgrim Queue Management System (SPQMS)",
    description="Software Engineering Project API for Tirumala Pilgrim Queue Management",
    version="2.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

@app.on_event("startup")
def on_startup():
    init_db()
    asyncio.create_task(background_reminder_loop())

# ============================================================
# AUTHENTICATION DEPENDENCIES
# ============================================================

def get_current_session(authorization: Optional[str] = Header(None)):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Session token missing or invalid format")
    token = authorization.split(" ")[1]
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT session_token, user_id, admin_id, staff_id, role 
        FROM SESSIONS 
        WHERE session_token = ?
    """, (token,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid session token or session expired")
        
    session_info = dict(row)
    
    # Fetch details based on role
    if session_info["role"] == "User" and session_info["user_id"]:
        cursor.execute("SELECT user_id, name, email, phone, age, gender, address FROM USERS WHERE user_id = ?", (session_info["user_id"],))
        u = cursor.fetchone()
        conn.close()
        if not u:
            raise HTTPException(status_code=401, detail="User not found")
        return {"role": "User", "user": dict(u), "token": token}
        
    elif session_info["role"] == "Admin" and session_info["admin_id"]:
        cursor.execute("SELECT admin_id, username, email, role FROM ADMINS WHERE admin_id = ?", (session_info["admin_id"],))
        a = cursor.fetchone()
        conn.close()
        if not a:
            raise HTTPException(status_code=401, detail="Admin not found")
        return {"role": "Admin", "admin": dict(a), "token": token}

    elif session_info["role"] == "Staff" and session_info["staff_id"]:
        cursor.execute("SELECT staff_id, username, email, badge_number FROM STAFF WHERE staff_id = ?", (session_info["staff_id"],))
        s = cursor.fetchone()
        conn.close()
        if not s:
            raise HTTPException(status_code=401, detail="Staff not found")
        return {"role": "Staff", "staff": dict(s), "token": token}
        
    conn.close()
    raise HTTPException(status_code=401, detail="Unauthorized role access")


def require_user(session: dict = Depends(get_current_session)):
    if session["role"] != "User":
        raise HTTPException(status_code=403, detail="Access denied: User portal only")
    return session["user"]


def require_admin(session: dict = Depends(get_current_session)):
    if session["role"] != "Admin":
        raise HTTPException(status_code=403, detail="Access denied: Admin permissions required")
    return session["admin"]


def require_staff(session: dict = Depends(get_current_session)):
    if session["role"] not in ["Staff", "Admin"]:
        raise HTTPException(status_code=403, detail="Access denied: Staff/Admin permissions required")
    return session.get("staff") or session.get("admin")


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def create_notification(cursor, user_id: int, title: str, message: str, type_: str = "info"):
    cursor.execute(
        "INSERT INTO NOTIFICATIONS (user_id, title, message, type) VALUES (?, ?, ?, ?)",
        (user_id, title, message, type_)
    )

def get_calendar_max_booking_date(base_date: Optional[datetime] = None) -> datetime:
    """Calculates the date exactly 3 calendar months later using month arithmetic and safe month-end handling."""
    if base_date is None:
        base_date = datetime.now()
    year = base_date.year
    month = base_date.month + 3
    while month > 12:
        year += 1
        month -= 12
    max_days = calendar.monthrange(year, month)[1]
    day = min(base_date.day, max_days)
    return base_date.replace(year=year, month=month, day=day)

def check_and_send_return_reminders():
    """Checks active temporary exit passes and triggers 15-minute return deadline notifications."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        now = datetime.now()
        
        cursor.execute("""
            SELECT qp.qr_id, qp.booking_id, qp.qr_data, qp.expiry_time, qp.reminder_time,
                   qp.reminder_sent, qp.status, b.user_id, d.darshan_name
            FROM QR_EXIT_PASS qp
            JOIN BOOKINGS b ON qp.booking_id = b.booking_id
            JOIN DARSHAN d ON b.darshan_id = d.darshan_id
            WHERE qp.status IN ('Approved', 'ACTIVE')
        """)
        passes = cursor.fetchall()
        
        for p in passes:
            qr_id = p["qr_id"]
            user_id = p["user_id"]
            expiry_str = p["expiry_time"]
            reminder_sent = p["reminder_sent"]
            
            if not expiry_str:
                continue
            try:
                expiry_dt = datetime.fromisoformat(expiry_str)
            except Exception:
                continue
                
            # If past expiry deadline, mark expired
            if now > expiry_dt:
                cursor.execute("UPDATE QR_EXIT_PASS SET status = 'EXPIRED', reminder_sent = 1 WHERE qr_id = ?", (qr_id,))
                create_notification(
                    cursor,
                    user_id,
                    "Temporary Exit Pass Expired",
                    f"Your temporary exit pass ({p['qr_data']}) expired at {expiry_dt.strftime('%I:%M %p')}. Please return to the queue compartment immediately.",
                    "error"
                )
                conn.commit()
                continue
                
            # Check if 15 minutes before return deadline
            if not reminder_sent:
                reminder_threshold = expiry_dt - timedelta(minutes=15)
                if now >= reminder_threshold:
                    time_display = expiry_dt.strftime("%I:%M %p")
                    cursor.execute("UPDATE QR_EXIT_PASS SET reminder_sent = 1 WHERE qr_id = ?", (qr_id,))
                    create_notification(
                        cursor,
                        user_id,
                        "Exit Pass Return Reminder",
                        f"Your temporary exit pass return time is approaching. Please return by {time_display}.",
                        "warning"
                    )
                    conn.commit()
                    
        conn.close()
    except Exception as e:
        pass

async def background_reminder_loop():
    """Background task to periodically evaluate exit pass reminders and expirations."""
    while True:
        try:
            check_and_send_return_reminders()
        except Exception:
            pass
        await asyncio.sleep(15)

def calculate_waiting_time(queue_count: int, avg_processing_mins: float, active_counters: int) -> int:
    """Legacy helper preserved only for isolated ML endpoints."""
    if active_counters <= 0:
        active_counters = 1
    wait_time = int((queue_count * avg_processing_mins) / active_counters)
    return max(5, wait_time)


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def home():
    return {
        "system": "Smart Pilgrim Queue Management System (SPQMS)",
        "status": "running",
        "version": "2.0.0"
    }


# ============================================================
# AUTHENTICATION APIs
# ============================================================

@app.post("/register")
def register(request: UserRegisterRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id FROM USERS WHERE email = ?", (request.email,))
    if cursor.fetchone():
        conn.close()
        raise HTTPException(status_code=400, detail="Email is already registered")
        
    hashed = hash_password(request.password)
    try:
        cursor.execute(
            """
            INSERT INTO USERS (name, email, phone, password, age, gender, address) 
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (request.name, request.email, request.phone, hashed, request.age, request.gender, request.address)
        )
        user_id = cursor.lastrowid
        
        # Add welcome notification
        create_notification(
            cursor, 
            user_id, 
            "Welcome to Smart Pilgrim System", 
            f"Greetings {request.name}! Your account has been registered successfully. You can now book sacred Darshan slots."
        )
        conn.commit()
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=f"Database error during registration: {str(e)}")
        
    conn.close()
    return {"message": "Registration successful"}


@app.post("/login")
def login(request: UserLoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT user_id, name, email, phone, password, age, gender, address FROM USERS WHERE email = ?", (request.email,))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    user = dict(row)
    if not verify_password(request.password, user["password"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid email or password")
        
    token = generate_session_token()
    cursor.execute("INSERT INTO SESSIONS (session_token, user_id, role) VALUES (?, ?, 'User')", (token, user["user_id"]))
    conn.commit()
    conn.close()
    
    return {
        "token": token,
        "role": "User",
        "user": {
            "user_id": user["user_id"],
            "name": user["name"],
            "email": user["email"],
            "phone": user["phone"],
            "age": user["age"],
            "gender": user["gender"],
            "address": user["address"]
        }
    }


@app.post("/admin/login")
def admin_login(request: AdminLoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT admin_id, username, email, password, role FROM ADMINS WHERE username = ? OR email = ?", 
        (request.username_or_email, request.username_or_email)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
        
    admin = dict(row)
    if not verify_password(request.password, admin["password"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
        
    token = generate_session_token()
    cursor.execute("INSERT INTO SESSIONS (session_token, admin_id, role) VALUES (?, ?, 'Admin')", (token, admin["admin_id"]))
    conn.commit()
    conn.close()
    
    return {
        "token": token,
        "role": "Admin",
        "admin": {
            "admin_id": admin["admin_id"],
            "username": admin["username"],
            "email": admin["email"],
            "role": admin["role"]
        }
    }


@app.post("/staff/login")
def staff_login(request: StaffLoginRequest):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute(
        "SELECT staff_id, username, email, password, badge_number FROM STAFF WHERE username = ? OR email = ?", 
        (request.username_or_email, request.username_or_email)
    )
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid staff credentials")
        
    staff = dict(row)
    if not verify_password(request.password, staff["password"]):
        conn.close()
        raise HTTPException(status_code=401, detail="Invalid staff credentials")
        
    token = generate_session_token()
    cursor.execute("INSERT INTO SESSIONS (session_token, staff_id, role) VALUES (?, ?, 'Staff')", (token, staff["staff_id"]))
    conn.commit()
    conn.close()
    
    return {
        "token": token,
        "role": "Staff",
        "staff": {
            "staff_id": staff["staff_id"],
            "username": staff["username"],
            "email": staff["email"],
            "badge_number": staff["badge_number"]
        }
    }


@app.get("/auth/me")
def get_me(session: dict = Depends(get_current_session)):
    return session


@app.post("/logout")
def logout(authorization: Optional[str] = Header(None)):
    if authorization and authorization.startswith("Bearer "):
        token = authorization.split(" ")[1]
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM SESSIONS WHERE session_token = ?", (token,))
        conn.commit()
        conn.close()
    return {"message": "Logged out successfully"}


# ============================================================
# DARSHAN MANAGEMENT APIs
# ============================================================

@app.get("/darshan")
def get_darshans():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT darshan_id, darshan_name, description, price, is_bookable, availability_status FROM DARSHAN")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/darshan/bookable")
def get_bookable_darshans():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT darshan_id, darshan_name, description, price, is_bookable, availability_status FROM DARSHAN WHERE is_bookable = 1 AND availability_status = 'Available'")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# DARSHAN BOOKING & PILGRIM APIs
# ============================================================

@app.post("/booking")
def create_booking(request: BookingCreateRequest, user: dict = Depends(require_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Date Validation (Requirement 2)
    today_date = datetime.now().date()
    try:
        booking_dt = datetime.strptime(request.booking_date, "%Y-%m-%d").date()
    except ValueError:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid booking date format. Expected YYYY-MM-DD.")
        
    if booking_dt < today_date:
        conn.close()
        raise HTTPException(status_code=400, detail="Past dates cannot be booked. Please select today or an eligible future date.")
        
    max_booking_dt = get_calendar_max_booking_date().date()
    if booking_dt > max_booking_dt:
        conn.close()
        raise HTTPException(
            status_code=400, 
            detail=f"Booking date exceeds the 3-month window. Darshan booking is only open through {max_booking_dt.strftime('%B %d, %Y')}."
        )

    # 2. Verify Darshan type exists and is bookable
    cursor.execute("SELECT darshan_id, darshan_name, price, is_bookable FROM DARSHAN WHERE darshan_id = ?", (request.darshan_id,))
    darshan = cursor.fetchone()
    if not darshan:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid Darshan Selection")
        
    if not darshan["is_bookable"]:
        conn.close()
        raise HTTPException(
            status_code=400, 
            detail="Sarvadarsanam / Free Darshan does not require online booking. You can walk-in directly to the queue compartment."
        )

    num_persons = max(1, request.number_of_persons)
    if len(request.pilgrims) < num_persons:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Please provide details for all {num_persons} pilgrim(s)")

    total_amount = darshan["price"] * num_persons
    
    # Calculate queue token position for that date
    cursor.execute(
        "SELECT COUNT(*) FROM BOOKINGS WHERE darshan_id = ? AND booking_date = ?",
        (request.darshan_id, request.booking_date)
    )
    current_count = cursor.fetchone()[0]
    queue_pos = current_count + 1
    
    # Fetch admin settings for this Darshan type (NO FORMULA)
    cursor.execute("SELECT estimated_waiting_time, active_counters FROM QUEUE_SETTINGS WHERE darshan_id = ?", (request.darshan_id,))
    q_settings = cursor.fetchone()
    admin_wait = q_settings["estimated_waiting_time"] if q_settings and q_settings["estimated_waiting_time"] is not None else None
    
    is_today = (booking_dt == today_date)
    
    try:
        # Create booking
        cursor.execute(
            """
            INSERT INTO BOOKINGS (user_id, darshan_id, booking_date, time_slot, number_of_persons, total_amount, payment_status, status, queue_position) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (user["user_id"], request.darshan_id, request.booking_date, request.time_slot, num_persons, total_amount, "Successful", "Confirmed", queue_pos)
        )
        booking_id = cursor.lastrowid
        
        # Add Pilgrim details
        for p in request.pilgrims[:num_persons]:
            cursor.execute(
                "INSERT INTO BOOKING_PILGRIMS (booking_id, name, age, gender) VALUES (?, ?, ?, ?)",
                (booking_id, p.name, p.age, p.gender)
            )
        
        # Queue entry management (Requirement 3):
        # Future bookings are NOT prematurely placed into the active queue
        if is_today:
            cursor.execute(
                "INSERT INTO QUEUE (booking_id, position, status, estimated_waiting_time) VALUES (?, ?, ?, ?)",
                (booking_id, queue_pos, "Waiting", int(admin_wait) if admin_wait is not None else 0)
            )
        
        # Update daily SSD tokens used if this is an SSD darshan
        cursor.execute("UPDATE SSD_QUOTA SET used_quota = used_quota + ? WHERE date = ?", (num_persons, request.booking_date))

        # Add Notification
        if is_today:
            notif_msg = f"Your booking (#BK-{booking_id}) for {darshan['darshan_name']} today ({request.time_slot}) has been confirmed. Assigned Queue position: #{queue_pos}."
        else:
            notif_msg = f"Your booking (#BK-{booking_id}) for {darshan['darshan_name']} on {request.booking_date} ({request.time_slot}) has been confirmed. Assigned Queue token: #{queue_pos}. Queue status will become available when your booking is eligible for queue admission on your visit date."

        create_notification(
            cursor,
            user["user_id"],
            "Darshan Booking Confirmed!",
            notif_msg,
            "success"
        )
        
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Booking creation failed: {str(e)}")
        
    conn.close()
    return {
        "booking_id": booking_id,
        "darshan_name": darshan["darshan_name"],
        "booking_date": request.booking_date,
        "time_slot": request.time_slot,
        "number_of_persons": num_persons,
        "total_amount": total_amount,
        "queue_position": queue_pos,
        "estimated_waiting_time": admin_wait,
        "is_future_booking": not is_today,
        "status": "Confirmed"
    }


@app.get("/bookings")
def get_user_bookings(user: dict = Depends(require_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.booking_id, b.booking_date, b.time_slot, b.number_of_persons, b.total_amount, b.payment_status, b.status, b.queue_position, b.darshan_id, d.darshan_name 
        FROM BOOKINGS b
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE b.user_id = ?
        ORDER BY b.booking_id DESC
    """, (user["user_id"],))
    booking_rows = cursor.fetchall()
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    results = []
    for b in booking_rows:
        bd = dict(b)
        bd["is_future_booking"] = bd["booking_date"] > today_str
        bd["is_today"] = bd["booking_date"] == today_str
        cursor.execute("SELECT pilgrim_id, name, age, gender FROM BOOKING_PILGRIMS WHERE booking_id = ?", (bd["booking_id"],))
        bd["pilgrims"] = [dict(p) for p in cursor.fetchall()]
        results.append(bd)
        
    conn.close()
    return results


@app.get("/booking/{booking_id}")
def get_booking(booking_id: int, user: dict = Depends(require_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT b.booking_id, b.booking_date, b.time_slot, b.number_of_persons, b.total_amount, b.payment_status, b.status, b.queue_position, b.darshan_id, d.darshan_name 
        FROM BOOKINGS b
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE b.booking_id = ? AND b.user_id = ?
    """, (booking_id, user["user_id"]))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found")
        
    bd = dict(row)
    today_str = datetime.now().strftime("%Y-%m-%d")
    bd["is_future_booking"] = bd["booking_date"] > today_str
    bd["is_today"] = bd["booking_date"] == today_str
    cursor.execute("SELECT pilgrim_id, name, age, gender FROM BOOKING_PILGRIMS WHERE booking_id = ?", (booking_id,))
    bd["pilgrims"] = [dict(p) for p in cursor.fetchall()]
    conn.close()
    return bd


# ============================================================
# QUEUE MANAGEMENT & ADMIN-CONFIGURED STATUS APIs
# ============================================================

@app.post("/queue/admit/{booking_id}")
def admit_to_queue(booking_id: int, user: dict = Depends(require_user)):
    """Admit an eligible booking to the active physical queue on its booked date."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT b.booking_id, b.user_id, b.darshan_id, b.booking_date, b.time_slot, b.status, d.darshan_name
        FROM BOOKINGS b
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE b.booking_id = ? AND b.user_id = ?
    """, (booking_id, user["user_id"]))
    booking = cursor.fetchone()
    
    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found.")
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    if booking["booking_date"] > today_str:
        conn.close()
        raise HTTPException(
            status_code=400,
            detail=f"Cannot admit to queue before the booked date. Your darshan is scheduled for {booking['booking_date']}."
        )
        
    if booking["status"] in ["Cancelled", "Completed"]:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Booking is {booking['status']} and cannot be admitted to queue.")
        
    # Prevent duplicate queue entries
    cursor.execute("SELECT queue_id, position, status FROM QUEUE WHERE booking_id = ?", (booking_id,))
    existing_q = cursor.fetchone()
    
    if existing_q:
        conn.close()
        return {
            "message": "Already admitted to queue.",
            "booking_id": booking_id,
            "queue_id": existing_q["queue_id"],
            "position": existing_q["position"],
            "status": existing_q["status"]
        }
        
    # Count waiting pilgrims for this darshan today
    cursor.execute("""
        SELECT COUNT(*) FROM QUEUE q
        JOIN BOOKINGS b ON q.booking_id = b.booking_id
        WHERE b.darshan_id = ? AND b.booking_date = ? AND q.status = 'Waiting'
    """, (booking["darshan_id"], booking["booking_date"]))
    pos = cursor.fetchone()[0] + 1
    
    cursor.execute("SELECT estimated_waiting_time FROM QUEUE_SETTINGS WHERE darshan_id = ?", (booking["darshan_id"],))
    qs = cursor.fetchone()
    admin_wait = qs["estimated_waiting_time"] if qs and qs["estimated_waiting_time"] is not None else 0
    
    cursor.execute(
        "INSERT INTO QUEUE (booking_id, position, status, estimated_waiting_time) VALUES (?, ?, 'Waiting', ?)",
        (booking_id, pos, int(admin_wait))
    )
    
    create_notification(
        cursor,
        user["user_id"],
        "Admitted to Darshan Queue",
        f"You have been admitted to the physical Darshan queue for {booking['darshan_name']}. Queue position: #{pos}.",
        "info"
    )
    conn.commit()
    conn.close()
    return {
        "message": "Successfully admitted to active queue.",
        "booking_id": booking_id,
        "position": pos,
        "status": "Waiting"
    }


@app.get("/queue/{booking_id}")
def get_queue_status(booking_id: int, user: dict = Depends(require_user)):
    """Retrieve queue status strictly using admin-configured waiting time and active counters."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT b.booking_id, b.darshan_id, d.darshan_name, b.booking_date, b.time_slot, b.queue_position, b.status as booking_status 
        FROM BOOKINGS b
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE b.booking_id = ? AND b.user_id = ?
    """, (booking_id, user["user_id"]))
    booking = cursor.fetchone()
    
    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found.")
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # Direct fetch of Admin-Entered Queue Settings for this Darshan type (NO FORMULA)
    cursor.execute(
        "SELECT estimated_waiting_time, active_counters, updated_at FROM QUEUE_SETTINGS WHERE darshan_id = ?",
        (booking["darshan_id"],)
    )
    q_settings = cursor.fetchone()
    admin_wait = q_settings["estimated_waiting_time"] if q_settings and q_settings["estimated_waiting_time"] is not None else None
    admin_counters = q_settings["active_counters"] if q_settings and q_settings["active_counters"] is not None else None
    settings_updated_at = q_settings["updated_at"] if q_settings else None
    
    # Requirement 3.3 A: Future booking
    if booking["booking_date"] > today_str:
        conn.close()
        return {
            "booking_id": booking["booking_id"],
            "darshan_id": booking["darshan_id"],
            "darshan_name": booking["darshan_name"],
            "booking_date": booking["booking_date"],
            "time_slot": booking["time_slot"],
            "is_future_booking": True,
            "queue_eligible": False,
            "is_admitted": False,
            "status": "Scheduled",
            "booking_status": booking["booking_status"],
            "message": f"Your Darshan is scheduled for {booking['booking_date']}. Queue status will become available when your booking is eligible for queue admission.",
            "estimated_waiting_time": None,
            "active_counters": None,
            "waiting_time_message": "Waiting time not yet updated by temple administration.",
            "counter_message": "Counter information not yet updated.",
            "last_updated": None
        }
        
    # Cancelled or Completed booking
    if booking["booking_status"] in ["Cancelled", "Completed"]:
        conn.close()
        return {
            "booking_id": booking["booking_id"],
            "darshan_id": booking["darshan_id"],
            "darshan_name": booking["darshan_name"],
            "booking_date": booking["booking_date"],
            "time_slot": booking["time_slot"],
            "is_future_booking": False,
            "queue_eligible": False,
            "is_admitted": False,
            "status": booking["booking_status"],
            "booking_status": booking["booking_status"],
            "message": f"This booking is {booking['booking_status']}.",
            "estimated_waiting_time": None,
            "active_counters": None
        }
        
    # Booking date is today: check if admitted into QUEUE table
    cursor.execute(
        "SELECT position, status FROM QUEUE WHERE booking_id = ?",
        (booking_id,)
    )
    q_row = cursor.fetchone()
    
    if not q_row or q_row["status"] == "Scheduled":
        conn.close()
        return {
            "booking_id": booking["booking_id"],
            "darshan_id": booking["darshan_id"],
            "darshan_name": booking["darshan_name"],
            "booking_date": booking["booking_date"],
            "time_slot": booking["time_slot"],
            "is_future_booking": False,
            "queue_eligible": True,
            "is_admitted": False,
            "status": "Eligible for Admission",
            "booking_status": booking["booking_status"],
            "message": "Your booking date has arrived! Please check in to be admitted to the physical Darshan queue compartment.",
            "estimated_waiting_time": admin_wait,
            "active_counters": admin_counters,
            "last_updated": settings_updated_at,
            "waiting_time_message": "Waiting time not yet updated by temple administration." if admin_wait is None else None,
            "counter_message": "Counter information not yet updated." if admin_counters is None else None,
            "is_estimate_disclaimer": "This is an estimated waiting time provided by temple administration, not a guaranteed waiting time."
        }
        
    queue = dict(q_row)
    
    # Count pilgrims ahead in queue
    cursor.execute("""
        SELECT COUNT(*) FROM QUEUE q
        JOIN BOOKINGS b ON q.booking_id = b.booking_id
        WHERE b.darshan_id = ? AND b.booking_date = ? AND q.status = 'Waiting' AND q.position < ?
    """, (booking["darshan_id"], booking["booking_date"], queue["position"]))
    people_ahead = cursor.fetchone()[0]
    
    conn.close()
    return {
        "booking_id": booking["booking_id"],
        "darshan_id": booking["darshan_id"],
        "darshan_name": booking["darshan_name"],
        "booking_date": booking["booking_date"],
        "time_slot": booking["time_slot"],
        "original_position": queue["position"],
        "current_position": people_ahead + 1,
        "people_ahead": people_ahead,
        "status": queue["status"],
        "booking_status": booking["booking_status"],
        "is_future_booking": False,
        "queue_eligible": True,
        "is_admitted": True,
        "estimated_waiting_time": admin_wait,
        "active_counters": admin_counters,
        "last_updated": settings_updated_at,
        "waiting_time_message": "Waiting time not yet updated by temple administration." if admin_wait is None else None,
        "counter_message": "Counter information not yet updated." if admin_counters is None else None,
        "is_estimate_disclaimer": "This is an estimated waiting time provided by temple administration, not a guaranteed waiting time."
    }


# ============================================================
# SSD DAILY QUOTA RELEASE APIs
# ============================================================

@app.get("/ssd/daily")
def get_daily_ssd_quota(date: Optional[str] = Query(None)):
    if not date:
        date = datetime.now().strftime("%Y-%m-%d")
        
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT quota_id, date, total_quota, used_quota, updated_at FROM SSD_QUOTA WHERE date = ?", (date,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return {
            "date": date,
            "total_quota": 0,
            "used_quota": 0,
            "remaining_quota": 0,
            "status": "Not Released"
        }
        
    ssd = dict(row)
    remaining = max(0, ssd["total_quota"] - ssd["used_quota"])
    return {
        "quota_id": ssd["quota_id"],
        "date": ssd["date"],
        "total_quota": ssd["total_quota"],
        "used_quota": ssd["used_quota"],
        "remaining_quota": remaining,
        "status": "Released"
    }


# ============================================================
# QR TEMPORARY EXIT PASS APIs (APPROVAL WORKFLOW)
# ============================================================

@app.post("/qr/request")
@app.post("/qr/generate")
def request_exit_pass(request: ExitPassRequest, user: dict = Depends(require_user)):
    """Pilgrim requests a temporary exit pass. Sets status to Pending Approval without generating an approved pass."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # 1. Verify booking belongs to user
    cursor.execute("SELECT booking_id, user_id, booking_date FROM BOOKINGS WHERE booking_id = ? AND user_id = ?", (request.booking_id, user["user_id"]))
    booking = cursor.fetchone()
    if not booking:
        conn.close()
        raise HTTPException(status_code=404, detail="Booking not found.")
        
    today_str = datetime.now().strftime("%Y-%m-%d")
    if booking["booking_date"] > today_str:
        conn.close()
        raise HTTPException(
            status_code=400, 
            detail="Temporary exit passes can only be requested on the day of your visit while waiting in the queue."
        )
        
    # 2. Verify user is currently in Queue with 'Waiting' status
    cursor.execute("SELECT queue_id, status FROM QUEUE WHERE booking_id = ?", (request.booking_id,))
    q_entry = cursor.fetchone()
    if not q_entry or q_entry["status"] != "Waiting":
        conn.close()
        raise HTTPException(
            status_code=400, 
            detail="Temporary exit passes can only be requested if you are currently waiting in the queue compartment."
        )

    # 3. Check existing QR exit pass
    cursor.execute("""
        SELECT qr_id, qr_data, status, expiry_time, reason, requested_return_time, expected_return_time, assigned_return_time 
        FROM QR_EXIT_PASS 
        WHERE booking_id = ? 
        ORDER BY qr_id DESC LIMIT 1
    """, (request.booking_id,))
    existing = cursor.fetchone()
    
    if existing:
        ext_pass = dict(existing)
        if ext_pass["status"] in ["Pending Approval", "Approved", "ACTIVE"]:
            if ext_pass.get("expiry_time"):
                try:
                    if datetime.now() > datetime.fromisoformat(ext_pass["expiry_time"]):
                        cursor.execute("UPDATE QR_EXIT_PASS SET status = 'EXPIRED' WHERE qr_id = ?", (ext_pass["qr_id"],))
                        conn.commit()
                        ext_pass["status"] = "EXPIRED"
                    else:
                        conn.close()
                        return ext_pass
                except Exception:
                    conn.close()
                    return ext_pass
            else:
                conn.close()
                return ext_pass

    # Create new exit pass request in Pending Approval state
    temp_ref = f"REQ-{secrets.token_hex(3).upper()}"
    now = datetime.now()
    now_iso = now.isoformat()
    # Default initial window placeholder (2 hours max from request) for database constraint, updated upon staff approval
    default_expiry = (now + timedelta(hours=2)).isoformat()
    
    try:
        cursor.execute(
            """
            INSERT INTO QR_EXIT_PASS (booking_id, qr_data, reason, requested_return_time, expected_return_time, status, generated_at, expiry_time) 
            VALUES (?, ?, ?, ?, ?, 'Pending Approval', ?, ?)
            """,
            (request.booking_id, temp_ref, request.reason, request.requested_return_time, request.requested_return_time, now_iso, default_expiry)
        )
        qr_id = cursor.lastrowid
        
        # Add Notification for Pilgrim
        create_notification(
            cursor,
            user["user_id"],
            "Exit Pass Request Submitted",
            f"Your temporary exit request ({temp_ref}) for '{request.reason}' (Requested return: {request.requested_return_time}) has been submitted and is pending temple staff approval.",
            "info"
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        raise HTTPException(status_code=500, detail=f"Exit pass request submission failed: {str(e)}")
        
    conn.close()
    return {
        "qr_id": qr_id,
        "booking_id": request.booking_id,
        "qr_data": temp_ref,
        "reason": request.reason,
        "requested_return_time": request.requested_return_time,
        "expected_return_time": request.requested_return_time,
        "status": "Pending Approval",
        "generated_at": now_iso
    }


@app.get("/staff/exit-requests")
def get_staff_exit_requests(status_filter: Optional[str] = None, staff: dict = Depends(require_staff)):
    """Temple staff views temporary exit pass requests for review."""
    check_and_send_return_reminders()
    conn = get_db_connection()
    cursor = conn.cursor()
    
    query = """
        SELECT qp.qr_id, qp.booking_id, qp.qr_data, qp.reason, qp.requested_return_time, qp.expected_return_time,
               qp.assigned_return_time, qp.status, qp.generated_at, qp.expiry_time,
               qp.approved_by, qp.approved_at, qp.rejected_by, qp.rejected_at, qp.rejection_reason, qp.staff_notes,
               b.booking_date, b.time_slot, d.darshan_name, u.name as pilgrim_name, u.phone as pilgrim_phone
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        JOIN USERS u ON b.user_id = u.user_id
    """
    if status_filter:
        query += " WHERE qp.status = ? ORDER BY qp.qr_id DESC"
        cursor.execute(query, (status_filter,))
    else:
        query += " ORDER BY CASE WHEN qp.status = 'Pending Approval' THEN 0 ELSE 1 END, qp.qr_id DESC"
        cursor.execute(query)
        
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/staff/exit-requests/{qr_id}/approve")
def approve_exit_request(qr_id: int, request: ExitPassApproveRequest, staff: dict = Depends(require_staff)):
    """Temple staff approves request, sets assigned return deadline, and activates the QR pass."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT qp.qr_id, qp.booking_id, qp.status, b.user_id, d.darshan_name
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE qp.qr_id = ?
    """, (qr_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Exit pass request not found.")
        
    pass_row = dict(row)
    if pass_row["status"] not in ["Pending Approval", "PENDING"]:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Request is already {pass_row['status']}.")
        
    now = datetime.now()
    deadline_str = request.assigned_return_time.strip()
    
    # Parse assigned return deadline
    try:
        if "T" in deadline_str:
            deadline_dt = datetime.fromisoformat(deadline_str)
        elif ":" in deadline_str and len(deadline_str) <= 8:
            parts = [int(p) for p in deadline_str.split(":")[:2]]
            deadline_dt = now.replace(hour=parts[0], minute=parts[1], second=0, microsecond=0)
            if deadline_dt <= now:
                deadline_dt += timedelta(days=1)
        else:
            deadline_dt = datetime.fromisoformat(deadline_str)
    except Exception:
        conn.close()
        raise HTTPException(status_code=400, detail="Invalid return deadline format. Please provide a valid timestamp or time.")
        
    if deadline_dt <= now:
        conn.close()
        raise HTTPException(status_code=400, detail="Assigned return deadline cannot be in the past or already expired.")
        
    staff_name = staff.get("username") or staff.get("badge_number") or "Staff"
    qr_token = f"PASS-{secrets.token_hex(4).upper()}"
    reminder_dt = deadline_dt - timedelta(minutes=15)
    
    cursor.execute("""
        UPDATE QR_EXIT_PASS
        SET status = 'Approved',
            qr_data = ?,
            assigned_return_time = ?,
            expiry_time = ?,
            approved_by = ?,
            approved_at = ?,
            staff_notes = ?,
            reminder_time = ?,
            reminder_sent = 0
        WHERE qr_id = ?
    """, (
        qr_token,
        deadline_dt.isoformat(),
        deadline_dt.isoformat(),
        staff_name,
        now.isoformat(),
        request.notes or "",
        reminder_dt.isoformat(),
        qr_id
    ))
    
    # Send in-app approval notification with assigned return deadline
    time_fmt = deadline_dt.strftime("%I:%M %p")
    create_notification(
        cursor,
        pass_row["user_id"],
        "Temporary Exit Pass Approved",
        f"Your temporary exit pass has been approved! Permitted return deadline: {time_fmt}. Please return to the queue compartment before this time.",
        "success"
    )
    
    conn.commit()
    conn.close()
    return {
        "message": "Temporary exit pass approved successfully.",
        "qr_id": qr_id,
        "qr_data": qr_token,
        "status": "Approved",
        "assigned_return_time": deadline_dt.isoformat(),
        "approved_by": staff_name,
        "reminder_time": reminder_dt.isoformat()
    }


@app.post("/staff/exit-requests/{qr_id}/reject")
def reject_exit_request(qr_id: int, request: ExitPassRejectRequest, staff: dict = Depends(require_staff)):
    """Temple staff rejects an exit pass request."""
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT qp.qr_id, qp.booking_id, qp.status, b.user_id, d.darshan_name
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE qp.qr_id = ?
    """, (qr_id,))
    row = cursor.fetchone()
    if not row:
        conn.close()
        raise HTTPException(status_code=404, detail="Exit pass request not found.")
        
    pass_row = dict(row)
    if pass_row["status"] not in ["Pending Approval", "PENDING"]:
        conn.close()
        raise HTTPException(status_code=400, detail=f"Request is already {pass_row['status']}.")
        
    staff_name = staff.get("username") or staff.get("badge_number") or "Staff"
    now = datetime.now()
    
    cursor.execute("""
        UPDATE QR_EXIT_PASS
        SET status = 'Rejected',
            rejected_by = ?,
            rejected_at = ?,
            rejection_reason = ?
        WHERE qr_id = ?
    """, (staff_name, now.isoformat(), request.rejection_reason, qr_id))
    
    # Send in-app rejection notification
    create_notification(
        cursor,
        pass_row["user_id"],
        "Temporary Exit Pass Rejected",
        f"Your temporary exit pass request was rejected by temple staff. Reason: {request.rejection_reason}.",
        "error"
    )
    conn.commit()
    conn.close()
    return {
        "message": "Exit pass request rejected.",
        "qr_id": qr_id,
        "status": "Rejected",
        "rejected_by": staff_name
    }


@app.get("/qr/{qr_id}")
def get_qr_pass(qr_id: int, user: dict = Depends(require_user)):
    check_and_send_return_reminders()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT qp.qr_id, qp.booking_id, qp.qr_data, qp.reason, qp.requested_return_time, qp.expected_return_time,
               qp.assigned_return_time, qp.status, qp.expiry_time, qp.generated_at,
               qp.approved_by, qp.approved_at, qp.rejected_by, qp.rejected_at, qp.rejection_reason, qp.staff_notes,
               b.booking_date, b.time_slot, d.darshan_name
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE qp.qr_id = ? AND b.user_id = ?
    """, (qr_id, user["user_id"]))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="QR Pass not found")
        
    pass_details = dict(row)
    if pass_details["status"] in ["Approved", "ACTIVE"] and pass_details.get("expiry_time"):
        if datetime.now() > datetime.fromisoformat(pass_details["expiry_time"]):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE QR_EXIT_PASS SET status = 'EXPIRED' WHERE qr_id = ?", (qr_id,))
            conn.commit()
            conn.close()
            pass_details["status"] = "EXPIRED"
        
    return pass_details


@app.get("/qr/booking/{booking_id}")
def get_qr_pass_by_booking(booking_id: int, user: dict = Depends(require_user)):
    check_and_send_return_reminders()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT qp.qr_id, qp.booking_id, qp.qr_data, qp.reason, qp.requested_return_time, qp.expected_return_time,
               qp.assigned_return_time, qp.status, qp.expiry_time, qp.generated_at,
               qp.approved_by, qp.approved_at, qp.rejected_by, qp.rejected_at, qp.rejection_reason, qp.staff_notes,
               b.booking_date, b.time_slot, d.darshan_name
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        WHERE qp.booking_id = ? AND b.user_id = ?
        ORDER BY qp.qr_id DESC LIMIT 1
    """, (booking_id, user["user_id"]))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        raise HTTPException(status_code=404, detail="QR Pass not found for this booking")
        
    pass_details = dict(row)
    if pass_details["status"] in ["Approved", "ACTIVE"] and pass_details.get("expiry_time"):
        if datetime.now() > datetime.fromisoformat(pass_details["expiry_time"]):
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("UPDATE QR_EXIT_PASS SET status = 'EXPIRED' WHERE qr_id = ?", (pass_details["qr_id"],))
            conn.commit()
            conn.close()
            pass_details["status"] = "EXPIRED"
        
    return pass_details


@app.post("/qr/verify")
def verify_qr_pass(request: QRVerifyRequest, staff: dict = Depends(require_staff)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    search_token = request.qr_data.strip()
    cursor.execute("""
        SELECT qp.qr_id, qp.booking_id, qp.qr_data, qp.reason, qp.requested_return_time, qp.assigned_return_time,
               qp.status, qp.expiry_time, qp.generated_at, b.user_id, b.booking_date, b.time_slot, d.darshan_name,
               u.name as user_name, u.phone as user_phone
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        JOIN USERS u ON b.user_id = u.user_id
        WHERE qp.qr_data = ? OR qp.qr_id = ?
    """, (search_token, search_token.replace("PASS-", "") if search_token.isdigit() else -1))
    row = cursor.fetchone()
    
    if not row:
        conn.close()
        return {
            "status": "INVALID",
            "message": "QR Exit Pass code does not exist in the system database."
        }
        
    qr_pass = dict(row)
    booking_id = qr_pass["booking_id"]
    staff_name = staff.get("username") or staff.get("badge_number") or "Staff"
    
    # Requirement 4.4: Check approval and validity
    if qr_pass["status"] in ["Pending Approval", "PENDING"]:
        conn.close()
        return {
            "status": "UNAPPROVED",
            "message": "Temporary exit pass request is still pending staff approval. Exit not authorized.",
            "pass_details": qr_pass
        }
        
    if qr_pass["status"] in ["Rejected", "REJECTED"]:
        conn.close()
        return {
            "status": "REJECTED",
            "message": "This temporary exit pass request was rejected by temple staff.",
            "pass_details": qr_pass
        }
    
    if qr_pass["status"] == "USED":
        conn.close()
        return {
            "status": "ALREADY USED",
            "message": "This temporary exit pass has already been scanned and verified.",
            "pass_details": qr_pass
        }
        
    if qr_pass["status"] == "EXPIRED":
        conn.close()
        return {
            "status": "EXPIRED",
            "message": "This temporary exit pass has expired.",
            "pass_details": qr_pass
        }
        
    # Check expiry against current time
    if qr_pass.get("expiry_time"):
        expiry = datetime.fromisoformat(qr_pass["expiry_time"])
        if datetime.now() > expiry:
            cursor.execute("UPDATE QR_EXIT_PASS SET status = 'EXPIRED' WHERE qr_id = ?", (qr_pass["qr_id"],))
            conn.commit()
            conn.close()
            return {
                "status": "EXPIRED",
                "message": "This temporary exit pass has passed its permitted return deadline and is expired.",
                "pass_details": qr_pass
            }
        
    now_iso = datetime.now().isoformat()
    cursor.execute(
        "UPDATE QR_EXIT_PASS SET status = 'USED', verified_by = ?, verified_at = ? WHERE qr_id = ?",
        (staff_name, now_iso, qr_pass["qr_id"])
    )
    cursor.execute("UPDATE QUEUE SET status = 'Exited Pass' WHERE booking_id = ?", (booking_id,))
    
    # Send Notification to User
    deadline_text = datetime.fromisoformat(qr_pass["expiry_time"]).strftime("%I:%M %p") if qr_pass.get("expiry_time") else "scheduled deadline"
    create_notification(
        cursor,
        qr_pass["user_id"],
        "QR Exit Verified by Staff",
        f"Your temporary exit pass ({qr_pass['qr_data']}) was verified by Temple Staff ({staff_name}) at {datetime.now().strftime('%H:%M:%S')}. Please return before {deadline_text}.",
        "info"
    )
    
    conn.commit()
    conn.close()
    
    qr_pass["status"] = "USED"
    return {
        "status": "VALID",
        "message": "Pass Verified! Temporary exit granted to pilgrim.",
        "pass_details": qr_pass,
        "verified_by": staff_name,
        "verified_at": now_iso
    }


# ============================================================
# NOTIFICATIONS APIs
# ============================================================

@app.get("/notifications")
def get_notifications(user: dict = Depends(require_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT notification_id, title, message, type, is_read, created_at FROM NOTIFICATIONS WHERE user_id = ? ORDER BY notification_id DESC",
        (user["user_id"],)
    )
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.put("/notifications/{notification_id}/read")
def mark_notification_read(notification_id: int, user: dict = Depends(require_user)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE NOTIFICATIONS SET is_read = 1 WHERE notification_id = ? AND user_id = ?", (notification_id, user["user_id"]))
    conn.commit()
    conn.close()
    return {"message": "Notification marked as read"}


# ============================================================
# ADMIN PORTAL APIs (QUEUE MANAGEMENT & QUOTA)
# ============================================================

@app.get("/admin/queue-settings")
def get_admin_queue_settings(admin: dict = Depends(require_admin)):
    """Fetch admin-managed waiting time and active counters for all Darshan types."""
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT d.darshan_id, d.darshan_name, d.description, d.price, d.is_bookable, d.availability_status,
               qs.setting_id, qs.estimated_waiting_time, qs.active_counters, qs.updated_at
        FROM DARSHAN d
        LEFT JOIN QUEUE_SETTINGS qs ON d.darshan_id = qs.darshan_id
        ORDER BY d.darshan_id ASC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.post("/admin/queue-settings")
def update_darshan_queue_settings(request: DarshanQueueSettingsUpdateRequest, admin: dict = Depends(require_admin)):
    """Admin updates manual waiting time and active counters for a specific Darshan type."""
    # Strict validation rules (Requirement 1.2)
    if request.estimated_waiting_time < 0:
        raise HTTPException(status_code=400, detail="Waiting time must be a non-negative number.")
        
    try:
        cnt = float(request.active_counters)
        if cnt < 0 or not cnt.is_integer():
            raise ValueError()
        counters_val = int(cnt)
    except Exception:
        raise HTTPException(status_code=400, detail="Active counters count must be a non-negative integer.")

    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT darshan_id, darshan_name FROM DARSHAN WHERE darshan_id = ?", (request.darshan_id,))
    darshan = cursor.fetchone()
    if not darshan:
        conn.close()
        raise HTTPException(status_code=404, detail="Darshan type not found.")
        
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute("SELECT setting_id FROM QUEUE_SETTINGS WHERE darshan_id = ?", (request.darshan_id,))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute("""
            UPDATE QUEUE_SETTINGS 
            SET estimated_waiting_time = ?, active_counters = ?, updated_at = ?
            WHERE darshan_id = ?
        """, (request.estimated_waiting_time, counters_val, now_str, request.darshan_id))
    else:
        cursor.execute("""
            INSERT INTO QUEUE_SETTINGS (darshan_id, estimated_waiting_time, active_counters, updated_at)
            VALUES (?, ?, ?, ?)
        """, (request.darshan_id, request.estimated_waiting_time, counters_val, now_str))
        
    conn.commit()
    conn.close()
    
    return {
        "message": f"Queue operational settings for '{darshan['darshan_name']}' updated successfully.",
        "darshan_id": request.darshan_id,
        "darshan_name": darshan["darshan_name"],
        "estimated_waiting_time": request.estimated_waiting_time,
        "active_counters": counters_val,
        "updated_at": now_str
    }


@app.get("/admin/dashboard-stats")
def get_admin_dashboard_stats(admin: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Active Queue Count
    cursor.execute("SELECT COUNT(*) FROM QUEUE WHERE status = 'Waiting'")
    queue_count = cursor.fetchone()[0]
    
    # 2. Total Bookings Today
    cursor.execute("SELECT COUNT(*) FROM BOOKINGS WHERE booking_date = ?", (today_str,))
    today_bookings = cursor.fetchone()[0]
    
    # 3. Today's SSD Quota stats
    cursor.execute("SELECT total_quota, used_quota FROM SSD_QUOTA WHERE date = ?", (today_str,))
    ssd_row = cursor.fetchone()
    if ssd_row:
        total_ssd = ssd_row["total_quota"]
        used_ssd = ssd_row["used_quota"]
        rem_ssd = max(0, total_ssd - used_ssd)
    else:
        total_ssd, used_ssd, rem_ssd = 0, 0, 0
        
    # 4. Active QR Exit Passes (Approved and active)
    cursor.execute("SELECT COUNT(*) FROM QR_EXIT_PASS WHERE status IN ('Approved', 'ACTIVE')")
    active_qrs = cursor.fetchone()[0]
    
    # 5. Pending Exit Pass Requests
    cursor.execute("SELECT COUNT(*) FROM QR_EXIT_PASS WHERE status = 'Pending Approval'")
    pending_qrs = cursor.fetchone()[0]
    
    # 6. Per-Darshan Settings Summary
    cursor.execute("""
        SELECT d.darshan_id, d.darshan_name, qs.estimated_waiting_time, qs.active_counters, qs.updated_at
        FROM DARSHAN d
        LEFT JOIN QUEUE_SETTINGS qs ON d.darshan_id = qs.darshan_id
        ORDER BY d.darshan_id ASC
    """)
    darshan_settings = [dict(r) for r in cursor.fetchall()]
    
    # Recent Bookings (top 5)
    cursor.execute("""
        SELECT b.booking_id, b.booking_date, b.time_slot, b.number_of_persons, b.total_amount, b.status, u.name as pilgrim_name, d.darshan_name
        FROM BOOKINGS b
        JOIN USERS u ON b.user_id = u.user_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        ORDER BY b.booking_id DESC LIMIT 5
    """)
    recent_bookings = [dict(r) for r in cursor.fetchall()]
    
    # Recent QR Exit Activity (top 5)
    cursor.execute("""
        SELECT qp.qr_id, qp.qr_data, qp.reason, qp.status, qp.generated_at, qp.verified_by, u.name as pilgrim_name
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN USERS u ON b.user_id = u.user_id
        ORDER BY qp.qr_id DESC LIMIT 5
    """)
    recent_qrs = [dict(r) for r in cursor.fetchall()]
    
    conn.close()
    return {
        "current_queue_count": queue_count,
        "darshan_settings": darshan_settings,
        "today_bookings_count": today_bookings,
        "ssd_total_quota": total_ssd,
        "ssd_used_quota": used_ssd,
        "ssd_remaining_quota": rem_ssd,
        "active_qr_passes": active_qrs,
        "pending_exit_requests": pending_qrs,
        "recent_bookings": recent_bookings,
        "recent_qr_activity": recent_qrs
    }


@app.post("/admin/ssd/release")
def release_ssd_quota(request: SSDQuotaReleaseRequest, admin: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT quota_id, used_quota FROM SSD_QUOTA WHERE date = ?", (request.date,))
    existing = cursor.fetchone()
    
    if existing:
        cursor.execute("UPDATE SSD_QUOTA SET total_quota = ?, updated_at = CURRENT_TIMESTAMP WHERE quota_id = ?", (request.total_quota, existing["quota_id"]))
        used = existing["used_quota"]
    else:
        cursor.execute("INSERT INTO SSD_QUOTA (date, total_quota, used_quota) VALUES (?, ?, 0)", (request.date, request.total_quota))
        used = 0
        
    conn.commit()
    conn.close()
    return {
        "message": f"SSD Daily Quota of {request.total_quota} tokens successfully released for date {request.date}",
        "date": request.date,
        "total_quota": request.total_quota,
        "used_quota": used,
        "remaining_quota": max(0, request.total_quota - used)
    }


@app.post("/admin/queue/settings")
def update_queue_settings(request: QueueSettingsUpdateRequest, admin: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO QUEUE_SETTINGS (active_counters, avg_processing_mins, queue_congestion_level) VALUES (?, ?, ?)",
        (request.active_counters, request.avg_processing_mins, request.queue_congestion_level)
    )
    conn.commit()
    conn.close()
    return {"message": "Queue operational settings updated successfully"}


@app.get("/admin/bookings/list")
def get_admin_bookings_list(admin: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT b.booking_id, b.booking_date, b.time_slot, b.number_of_persons, b.total_amount, b.status, b.queue_position, u.name as pilgrim_name, u.email as pilgrim_email, d.darshan_name
        FROM BOOKINGS b
        JOIN USERS u ON b.user_id = u.user_id
        JOIN DARSHAN d ON b.darshan_id = d.darshan_id
        ORDER BY b.booking_id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/admin/qr/activity")
def get_admin_qr_activity(admin: dict = Depends(require_admin)):
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT qp.qr_id, qp.booking_id, qp.qr_data, qp.reason, qp.expected_return_time, qp.status, qp.generated_at, qp.expiry_time, qp.verified_by, qp.verified_at, u.name as pilgrim_name
        FROM QR_EXIT_PASS qp
        JOIN BOOKINGS b ON qp.booking_id = b.booking_id
        JOIN USERS u ON b.user_id = u.user_id
        ORDER BY qp.qr_id DESC
    """)
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ============================================================
# CROWD PREDICTION (ML — ISOLATED)
# ============================================================

@app.post("/predict/crowd")
def crowd_prediction(request: CrowdPredictionRequest):
    data = request.model_dump()
    return predict_crowd(data)


# ============================================================
# WAITING-TIME PREDICTION (ML — ISOLATED)
# ============================================================

@app.post("/predict/waiting-time")
def waiting_time_prediction(request: WaitingTimePredictionRequest):
    data = request.model_dump()
    return predict_waiting_time(data)