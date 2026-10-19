# Smart Pilgrim Queue Management System (SPQMS)

A full-stack Software Engineering (SWE) project built for Tirumala Temple pilgrim queue tracking, Darshan slot booking, daily SSD token quota releases, temporary QR exit pass management, and temple staff gate verification.

---

## 🌟 Architecture & Tech Stack

* **Frontend**: React.js (v19), React Router (v7), Vanilla CSS
* **Backend**: Python (3.9+), FastAPI, Uvicorn
* **Database**: SQLite3 (`backend/darshan_system.db`)
* **Authentication**: PBKDF2 Password Hashing (`pbkdf2_sha256`), Session Tokens, Role-Based Access Control (User, Admin, Staff)

---

## 🏛️ System Modules & Features

### 1. Pilgrim (User) Portal
* **Account Registration**: Complete details (Name, Email, Phone, Age, Gender, Address, Password).
* **Darshan Packages View**: Displays pre-booked Darshan categories. Excludes Sarvadarsanam (Free Darshan) from online booking, marking it as direct walk-in only.
* **Darshan Booking & Pilgrim Details**: Supports booking multiple pilgrims per transaction (Name, Age, Gender for each pilgrim). Includes a simulated payment gateway step.
* **Deterministic Queue Status**: Live position tracking (`#BK-ID`), pilgrims ahead, active counters, queue congestion status (`LOW`, `MEDIUM`, `HIGH`), and deterministic wait time calculation.
* **SSD Token Availability**: Pilgrim view for daily SSD quota released by Admin (Total Released, Used, Remaining).
* **QR Temporary Exit Pass**: Requests temporary exit pass with reason selection and expected return time picker (only accessible for pilgrims currently in queue).
* **Notification System**: Real-time internal alerts for booking confirmations and QR verification actions.

### 2. Admin Portal (50% Management Module)
* **Admin Login**: Role-protected login (`admin@tirumala.org`).
* **Admin Dashboard**: Real-time counters for Active Queue Count, Today's Bookings, Today's SSD Quota, Active QR Passes.
* **Queue Operational Settings**: Admin can modify Active Counters, Avg Processing Mins, and Queue Congestion Level.
* **Daily SSD Quota Release**: Select date, enter total quota release, view used and remaining tokens.
* **Audit Logs**: Live tables for Recent Pilgrim Bookings Audit and QR Exit Activity.

### 3. Temple Staff Verification Portal
* **Staff Login**: Role-protected login (`staff@tirumala.org`).
* **Gate Verification Apparatus**: Staff scans or manually inputs QR Exit Pass codes (`PASS-XXXXXX`).
* **Instant Verification**: Checks validity (`VALID`, `EXPIRED`, `ALREADY USED`, `INVALID`), displays pilgrim name, phone, booking ID, reason, expected return time, and logs staff badge verification.

---

## 🚀 How to Run the Project (Windows PowerShell)

### Prerequisites
- Node.js (v16+)
- Python (3.9+)

### Step 1: Start Backend (FastAPI)
```powershell
# Activate Virtual Environment (from project root)
.\venv\Scripts\Activate.ps1

# Install Dependencies (if running first time)
pip install fastapi uvicorn pydantic scikit-learn pandas numpy joblib

# Start FastAPI server
python -m uvicorn backend.main:app --reload --port 8000
```
Backend API runs at: `http://localhost:8000` (Swagger UI: `http://localhost:8000/docs`)

### Step 2: Start Frontend (React)
```powershell
# Open a second terminal window and navigate to frontend
cd frontend

# Install npm packages (if running first time)
npm install

# Start React development server
npm start
```
Frontend Web App runs at: `http://localhost:3000`

---

## 🔑 Default Demo Credentials

* **Pilgrim Account**:
  * Email: `pilgrim@example.com`
  * Password: `user123`

* **Admin Portal**:
  * Username / Email: `admin@tirumala.org`
  * Password: `admin123`

* **Temple Staff Portal**:
  * Username / Email: `staff@tirumala.org`
  * Password: `staff123`
  * Badge Number: `BADGE-101`

---

## 📊 Database Schema (SQLite)

1. `USERS`: `user_id`, `name`, `email`, `phone`, `password`, `age`, `gender`, `address`
2. `ADMINS`: `admin_id`, `username`, `email`, `password`, `role`
3. `STAFF`: `staff_id`, `username`, `email`, `password`, `badge_number`
4. `SESSIONS`: `session_token`, `user_id`, `admin_id`, `staff_id`, `role`
5. `DARSHAN`: `darshan_id`, `darshan_name`, `description`, `price`, `is_bookable`, `availability_status`
6. `BOOKINGS`: `booking_id`, `user_id`, `darshan_id`, `booking_date`, `time_slot`, `number_of_persons`, `total_amount`, `payment_status`, `status`, `queue_position`
7. `BOOKING_PILGRIMS`: `pilgrim_id`, `booking_id`, `name`, `age`, `gender`
8. `QUEUE`: `queue_id`, `booking_id`, `position`, `status`, `estimated_waiting_time`
9. `QUEUE_SETTINGS`: `setting_id`, `avg_processing_mins`, `active_counters`, `queue_congestion_level`
10. `SSD_QUOTA`: `quota_id`, `date`, `total_quota`, `used_quota`
11. `QR_EXIT_PASS`: `qr_id`, `booking_id`, `qr_data`, `reason`, `expected_return_time`, `status`, `expiry_time`, `verified_by`, `verified_at`
12. `NOTIFICATIONS`: `notification_id`, `user_id`, `title`, `message`, `type`, `is_read`
