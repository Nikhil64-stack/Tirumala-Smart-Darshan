from pydantic import BaseModel
from typing import Optional

# ============================================================
# SWE SCHEMAS
# ============================================================

class UserRegister(BaseModel):
    name: str
    email: str
    password: str
    role: str = "user"  # default user role, can also be admin/staff for setup

class UserLogin(BaseModel):
    email: str
    password: str

class BookingCreate(BaseModel):
    user_id: int
    darshan_type: str
    date: str
    slot: str
    pilgrims_count: int
    pilgrim_details: Optional[str] = None

class QueueUpdate(BaseModel):
    booking_id: str
    queue_position: int
    queue_count: int
    queue_status: str
    waiting_time: int
    people_processed_per_hour: int

class TokenUpdate(BaseModel):
    token_id: str
    booking_id: Optional[str] = None
    status: str

class ExitPassVerify(BaseModel):
    pass_id: str

class SsdQuotaRelease(BaseModel):
    date: str
    total_released: int