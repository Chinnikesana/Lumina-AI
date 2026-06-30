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
        
    # AI/LLM Settings
    GOOGLE_API_KEY: str = ""  # Kept as fallback
    OPENROUTER_API_KEY: str = ""  # OpenRouter fallback
    GROQ_API_KEY: str = ""  # Primary LLM (Groq free tier)
    HF_API_KEY: str = ""  # HuggingFace Inference API (free tier embeddings)
    
    class Config:
        env_file = ".env"
        case_sensitive = True

# Create settings instance
settings = Settings()

# Print configuration status (only in development)
if settings.ENVIRONMENT == "development":
    print("🔧 Configuration loaded successfully!")
    print(f"📊 Environment: {settings.ENVIRONMENT}")
    print(f"🗄️  Database URL: {settings.DATABASE_URL[:30]}...")
    print(f"🔑 JWT Secret: {'*' * 20}")
    print(f"⏰ JWT Expiry: {settings.JWT_EXPIRE_MINUTES} minutes")
    print(f"🌐 CORS Origins: {settings.CORS_ORIGINS}")
    print(f"🔐 Supabase Anon Key: {'*' * 20}")
    print(f"🔐 Supabase Service Role Key: {'*' * 20}")   # 👈 print safely
    print(f"🤖 Google API Key: {'*' * 20 if settings.GOOGLE_API_KEY else 'Not set'}")
    print(f"🤖 OpenRouter API Key: {'*' * 20 if settings.OPENROUTER_API_KEY else 'Not set'}")
    print(f"🤖 Groq API Key: {'*' * 20 if settings.GROQ_API_KEY else 'Not set'}")
    print(f"🤖 HuggingFace API Key: {'*' * 20 if settings.HF_API_KEY else 'Not set'}")
    print("✅ All environment variables loaded correctly!")
