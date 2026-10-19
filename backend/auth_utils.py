import hashlib
import secrets

def hash_password(password: str) -> str:
    """Hashes a password using PBKDF2-HMAC-SHA256 with a unique salt."""
    salt = secrets.token_hex(16)
    iterations = 100000
    dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
    return f"pbkdf2_sha256${iterations}${salt}${dk.hex()}"

def verify_password(password: str, hashed_password: str) -> bool:
    """Verifies a password against its PBKDF2 hashed value."""
    try:
        parts = hashed_password.split('$')
        if len(parts) != 4:
            return False
        algo, iterations_str, salt, orig_hash = parts
        if algo != 'pbkdf2_sha256':
            return False
        iterations = int(iterations_str)
        dk = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
        return secrets.compare_digest(dk.hex(), orig_hash)
    except Exception:
        return False

def generate_session_token() -> str:
    """Generates a secure random session token."""
    return secrets.token_hex(32)
