"""
User management endpoints
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from ..core.database import get_db
from ..core.security import get_current_user_token, get_password_hash
from ..core.logger import get_logger
from ..core.supabase_client import supabase_client
from ..models.models import User, UserResponse, UserUpdate, TokenData

logger = get_logger(__name__)
router = APIRouter()

async def get_current_user(
    token_data: dict = Depends(get_current_user_token)
) -> dict:
    """Get current authenticated user"""
    user_id = token_data.get("user_id") or token_data.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token"
        )
    
    user_response = supabase_client.table('users').select('*').eq('user_id', user_id).execute()
    
    if not user_response.data:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    user = user_response.data[0]
    
    if user['status'] != "active":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is not active"
        )
    
    return user

@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user)):
    """
    Get current user information
    
    Returns the authenticated user's profile information
    """
    logger.info(f"User info requested: {current_user['email']}")
    return UserResponse(**current_user)

@router.get("/users")
async def get_users(limit: int = Query(10, ge=1, le=100)):
    """
    Get users with limit parameter
    
    - **limit**: Number of users to return (1-100, default: 10)
    """
    try:
        users_response = supabase_client.table('users').select('user_id, first_name, last_name, email, created_at, status').limit(limit).execute()
        
        if not users_response.data:
            return {"users": [], "count": 0}
        
        logger.info(f"Retrieved {len(users_response.data)} users")
        return {"users": users_response.data, "count": len(users_response.data)}
        
    except Exception as e:
        logger.error(f"Error retrieving users: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve users"
        )

@router.put("/update", response_model=UserResponse)
async def update_user(
    user_update: UserUpdate,
    current_user: dict = Depends(get_current_user)
):
    """
    Update current user information
    
    - **first_name**: Updated first name (optional)
    - **last_name**: Updated last name (optional)
    - **email**: Updated email address (optional)
    """
    try:
        update_data = user_update.dict(exclude_unset=True)
        
        # Check if email is being updated and if it's already taken
        if "email" in update_data and update_data["email"] != current_user["email"]:
            existing_user_response = supabase_client.table('users').select('*').eq('email', update_data["email"]).execute()
            
            if existing_user_response.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email already registered"
                )
        
        # Update user in Supabase
        update_response = supabase_client.table('users').update(update_data).eq('user_id', current_user['user_id']).execute()
        
        if not update_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to update user"
            )
        
        updated_user = update_response.data[0]
        logger.info(f"User updated: {updated_user['email']}")
        return UserResponse(**updated_user)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user"
        )

@router.delete("/delete", status_code=status.HTTP_200_OK)
async def delete_user(
    current_user: dict = Depends(get_current_user)
):
    """
    Delete current user account
    
    This action is irreversible and will permanently delete the user's account
    """
    try:
        logger.info(f"User account deletion requested: {current_user['email']}")
        
        # Soft delete by setting status to deleted
        delete_response = supabase_client.table('users').update({'status': 'deleted'}).eq('user_id', current_user['user_id']).execute()
        
        if not delete_response.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to delete user account"
            )
        
        logger.info(f"User account deleted: {current_user['email']}")
        return {"message": "Account deleted successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting user: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete user account"
        )
