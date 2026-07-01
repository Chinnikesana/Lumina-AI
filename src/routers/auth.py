"""
Authentication endpoints
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.database import get_db
from ..core.security import verify_password, get_password_hash, create_token_response
from ..core.logger import get_logger
from ..core.supabase_client import supabase_client
from ..models.models import User, UserCreate, UserLogin, TokenResponse, UserResponse

logger = get_logger(__name__)
router = APIRouter()

@router.post("/signup", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def signup(user_data: UserCreate):
    """
    Create a new user account
    
    - **first_name**: User's first name
    - **last_name**: User's last name  
    - **email**: User's email address (must be unique)
    - **password**: User's password (min 6 characters)
    """
    try:
        # Step 1: Create user in Supabase Auth
        try:
            auth_res = supabase_client.auth.sign_up({
                "email": user_data.email,
                "password": user_data.password,
            })
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Supabase Auth signup failed: {error_msg}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg
            )

        # Step 2: Extract user_id from Supabase Auth response
        auth_user = getattr(auth_res, 'user', None)
        if not auth_user or not getattr(auth_user, 'id', None):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create account. Email may already be registered."
            )
        
        auth_user_id = str(auth_user.id)

        # Step 3: Hash password and insert into users table
        hashed_password = get_password_hash(user_data.password)
        
        new_user_data = {
            "user_id": auth_user_id,
            "first_name": user_data.first_name,
            "last_name": user_data.last_name,
            "email": user_data.email,
            "password": hashed_password,
            "created_at": datetime.utcnow().isoformat(),
            "status": "active"
        }
            
        user_response = supabase_client.table('users').insert(new_user_data).execute()
        if not user_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user in database"
            )

        created_user = user_response.data[0]
        logger.info(f"New user created: {created_user['email']}")

        # Step 4: Create and return token response
        user_response_data = {
            "user_id": str(created_user['user_id']),
            "first_name": created_user['first_name'],
            "last_name": created_user['last_name'],
            "email": created_user['email']
        }
        token_response = create_token_response(user_response_data)
        return TokenResponse(**token_response)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in signup: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user account"
        )

@router.post("/login", response_model=TokenResponse)
async def login(login_data: UserLogin):
    """
    Authenticate user and return JWT token
    
    - **email**: User's email address
    - **password**: User's password.
    """
    try:
        # Find user by email using Supabase
        user_response = supabase_client.table('users').select('*').eq('email', login_data.email).execute()
        
        if not user_response.data:
            logger.warning(f"Login attempt with non-existent email: {login_data.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        user = user_response.data[0]
        
        # Check password
        if not verify_password(login_data.password, user['password']):
            logger.warning(f"Invalid password attempt for email: {login_data.email}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        # Check user status
        if user['status'] != "active":
            logger.warning(f"Login attempt for inactive user: {login_data.email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is not active"
            )
        
        # Update last login
        supabase_client.table('users').update({
            'last_login': datetime.utcnow().isoformat()
        }).eq('user_id', user['user_id']).execute()
        
        logger.info(f"Successful login: {user['email']}")
        
        # Create token response
        user_response_data = {
            "user_id": str(user['user_id']),
            "first_name": user['first_name'],
            "last_name": user['last_name'],
            "email": user['email']
        }
        
        token_response = create_token_response(user_response_data)
        return TokenResponse(**token_response)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in login: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to authenticate user"
        )

@router.put("/logout", status_code=status.HTTP_200_OK)
async def logout():
    """
    Logout user (client-side token removal)
    
    Note: Since we're using stateless JWT tokens, logout is handled
    client-side by removing the token from storage.
    """
    logger.info("User logout")
    return {"message": "Logged out successfully"}
