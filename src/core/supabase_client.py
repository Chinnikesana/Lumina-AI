"""
Supabase client configuration
"""

from supabase import create_client, Client
from .config import settings

def get_supabase_client() -> Client:
    """Get Supabase client instance"""
    try:
        supabase: Client = create_client(settings.SUPABASE_URL, settings.SERVICE_ROLE_KEY)
        print("✅ Supabase client created successfully!")
        return supabase
    except Exception as e:
        print(f"❌ Failed to create Supabase client: {str(e)}")
        raise e

# Global Supabase client instance
supabase_client = get_supabase_client()
