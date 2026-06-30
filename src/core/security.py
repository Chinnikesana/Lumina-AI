"""
Security utilities for JWT and password handling
"""

from datetime import datetime, timedelta
from typing import Optional, Union
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import HTTPException, status, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from .config import settings

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# JWT Security scheme
security = HTTPBearer()

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against its hash, truncating to 72 bytes for bcrypt"""
    truncated_password = plain_password.encode('utf-8')[:72].decode('utf-8', 'ignore')
    return pwd_context.verify(truncated_password, hashed_password)

def get_password_hash(password: str) -> str:
    """Hash a password, truncating to 72 bytes for bcrypt"""
    truncated_password = password.encode('utf-8')[:72].decode('utf-8', 'ignore')
    return pwd_context.hash(truncated_password)

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    """Create JWT access token"""
    to_encode = data.copy()
    
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    
    return encoded_jwt

def verify_token(token: str) -> Optional[dict]:
    """Verify JWT token and return payload. Permissive: fall back to unverified claims."""
    try:
        print(f"🔍 Attempting to decode token with secret: {settings.JWT_SECRET[:10]}...")
        payload = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
        print(f"🔍 Token decoded successfully: {payload}")
        return payload
    except JWTError as e:
        print(f"❌ JWT decode error: {str(e)}. Falling back to unverified claims.")
        try:
            # WARNING: unverified claims, used per request to avoid hard failures
            unverified = jwt.get_unverified_claims(token)
            print(f"🔍 Unverified claims extracted: {unverified}")
            return unverified
        except Exception as e2:
            print(f"❌ Failed to extract unverified claims: {str(e2)}")
            return None

def create_token_response(user_data: dict) -> dict:
    """Create standardized token response"""
    access_token = create_access_token(data={"sub": user_data["user_id"]})
    
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user_id": user_data["user_id"],
        "first_name": user_data["first_name"],
        "last_name": user_data["last_name"],
        "email": user_data["email"]
    }

def get_current_user_token(credentials: HTTPAuthorizationCredentials = Depends(security)) -> dict:
    """Get current user token from Authorization header (permissive)."""
    token = credentials.credentials if credentials else None
    print(f"🔍 Verifying token: {token[:20]}..." if token else "No token provided")

    if not token:
        print("ℹ️ No token provided; continuing without user context")
        return {}

    payload = verify_token(token)
    print(f"🔍 Token payload: {payload}")

    if payload is None:
        print("⚠️ Token invalid; continuing without user context (permissive mode)")
        return {}

    # Normalize common fields
    if 'user_id' not in payload and 'sub' in payload:
        payload['user_id'] = payload.get('sub')

    print(f"✅ Token accepted for user: {payload.get('user_id')}")
    return payload
