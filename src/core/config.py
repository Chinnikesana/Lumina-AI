"""
Configuration settings for Lumina AI Tutor Backend
"""

import os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    """Application settings"""
    
    # Database (Supabase PostgreSQL)
    DATABASE_URL: str  # PostgreSQL connection string
    SUPABASE_URL: str  # Supabase API URL
    ANON_KEY: str
    SERVICE_ROLE_KEY: str   # 👈 Add this
    
    # JWT Settings
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRE_MINUTES: int = 60
    
    # Environment
    ENVIRONMENT: str = "development"
    
    # CORS
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]
        
    # Server Settings
    PORT: int = 8080
    
    # AI/LLM Settings
    GOOGLE_API_KEY: str = ""  # Kept as fallback
    GOOGLE_API_KEY_NARRATION: str = ""  # Google API key for narration
    OPENROUTER_API_KEY: str = ""  # OpenRouter fallback
    OPENROUTER_API_KEY2: Optional[str] = ""  # Optional second OpenRouter key
    GROQ_API_KEY: str = ""  # Primary LLM (Groq free tier)
    GROQ_API_KEY_2: Optional[str] = ""  # Optional second Groq key for fallback
    HF_API_KEY: str = ""  # HuggingFace Inference API (free tier embeddings)
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Create settings instance
settings = Settings()

# Print configuration status (only in development)
if settings.ENVIRONMENT == "development":
    print("[OK] Configuration loaded successfully!")
    print(f"[ENV] Environment: {settings.ENVIRONMENT}")
    print(f"[DB]  Database URL: {settings.DATABASE_URL[:30]}...")
    print(f"[JWT] JWT Secret: {'*' * 20}")
    print(f"[JWT] JWT Expiry: {settings.JWT_EXPIRE_MINUTES} minutes")
    print(f"[CORS] CORS Origins: {settings.CORS_ORIGINS}")
    print(f"[KEY] Supabase Anon Key: {'*' * 20}")
    print(f"[KEY] Supabase Service Role Key: {'*' * 20}")
    print(f"[AI] Google API Key: {'*' * 20 if settings.GOOGLE_API_KEY else 'Not set'}")
    print(f"[AI] OpenRouter API Key: {'*' * 20 if settings.OPENROUTER_API_KEY else 'Not set'}")
    print(f"[AI] Groq API Key: {'*' * 20 if settings.GROQ_API_KEY else 'Not set'}")
    print(f"[AI] HuggingFace API Key: {'*' * 20 if settings.HF_API_KEY else 'Not set'}")
    print("[OK] All environment variables loaded correctly!")

