from pydantic import BaseModel
from typing import Optional, List

# ============================================================
# AUTHENTICATION SCHEMAS
# ============================================================

class UserRegisterRequest(BaseModel):
    name: str
    email: str
    phone: str
    password: str
    age: Optional[int] = None
    gender: Optional[str] = None
    address: Optional[str] = None

class UserLoginRequest(BaseModel):
    email: str
    password: str

class AdminLoginRequest(BaseModel):
    username_or_email: str
    password: str

class StaffLoginRequest(BaseModel):
    username_or_email: str
    password: str


# ============================================================
# BOOKING & PILGRIM SCHEMAS
# ============================================================

class PilgrimDetailSchema(BaseModel):
    name: str
    age: int
    gender: str

class BookingCreateRequest(BaseModel):
    darshan_id: int
    booking_date: str
    time_slot: str
    number_of_persons: int = 1
    pilgrims: List[PilgrimDetailSchema]


# ============================================================
# SSD QUOTA SCHEMAS
# ============================================================

class SSDQuotaReleaseRequest(BaseModel):
    date: str
    total_quota: int


# ============================================================
# QR EXIT PASS SCHEMAS
# ============================================================

class QRGenerateRequest(BaseModel):
    booking_id: int
    reason: str = "Personal"
    expected_return_time: str = "1 Hour"

class ExitPassRequest(BaseModel):
    booking_id: int
    reason: str = "Personal"
    requested_return_time: str = "1 Hour"

class ExitPassApproveRequest(BaseModel):
    assigned_return_time: str
    notes: Optional[str] = None

class ExitPassRejectRequest(BaseModel):
    rejection_reason: Optional[str] = "Request denied by temple authority"

class QRVerifyRequest(BaseModel):
    qr_data: str


# ============================================================
# QUEUE SETTINGS SCHEMAS
# ============================================================

class QueueSettingsUpdateRequest(BaseModel):
    active_counters: int
    avg_processing_mins: float
    queue_congestion_level: str

class DarshanQueueSettingsUpdateRequest(BaseModel):
    darshan_id: int
    estimated_waiting_time: float
    active_counters: int

class QueueAdmissionRequest(BaseModel):
    booking_id: int


# ============================================================
# ML SCHEMAS (ISOLATED)
# ============================================================

class CrowdPredictionRequest(BaseModel):
    date: str
    day_of_week: str
    month: str
    is_weekend: int
    is_public_holiday: int
    festival_name: str
    festival_impact: str
    time_slot: str
    darshan_type: str

class WaitingTimePredictionRequest(BaseModel):
    date: str
    day_of_week: str
    month: str
    time_slot: str
    darshan_type: str
    current_queue_count: int
    waiting_compartments: int
    queue_occupancy_percent: float
    people_entering_per_hour: int
    people_processed_per_hour: int
    current_crowd_level: str
    is_weekend: int
    is_public_holiday: int
    festival_impact: str
    ssd_tokens_issued: int
    ssd_tokens_remaining: int