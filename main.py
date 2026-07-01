"""
Lumina AI Tutor Backend
FastAPI application entry point
"""

import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.core.config import settings
from src.core.logger import setup_logging, get_logger
from src.core.supabase_client import supabase_client
from src.routers import auth, user, documents, narrations, streaming, summary, knowledgetest, chat, notes

# Setup logging
setup_logging()
logger = get_logger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    print("🚀 Starting Lumina AI Tutor Backend...")
    logger.info("Starting Lumina AI Tutor Backend")
    
    # Test Supabase connection
    try:
        # Test Supabase connection
        print("🔗 Testing Supabase connection...")
        response = supabase_client.table('users').select('*').limit(1).execute()
        print("✅ Supabase connection successful!")
        logger.info("Supabase connection successful")
    except Exception as e:
        print(f"⚠️  Supabase connection test failed: {str(e)}")
        print("💡 This is normal if the users table doesn't exist yet")
        logger.warning(f"Supabase connection test failed: {str(e)}")
    
    
    # Load routers
    print("📋 Loading API routers...")
    print("   ✅ Authentication routes (/api/auth)")
    print("   ✅ User management routes (/api/user)")
    print("   ✅ Document management routes (/api/documents)")
    print("   ✅ Narration management routes (/api/narrations)")
    print("   ✅ Streaming routes (/api/streaming)")
    logger.info("API routers loaded successfully")
    
    yield
    
    # Shutdown
    print("🛑 Shutting down Lumina AI Tutor Backend")
    logger.info("Shutting down Lumina AI Tutor Backend")

# Create FastAPI app
app = FastAPI(
    title="Lumina AI Tutor API",
    description="Backend API for Lumina AI Tutor application",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174",'https://lumina-ai-bblg50n87-chinni-kesana-s-projects.vercel.app'],  # Add your frontend URLs
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all requests with response time"""
    start_time = time.time()
    
    # Log request
    logger.info(f"Request: {request.method} {request.url.path}")
    
    try:
        response = await call_next(request)
        process_time = time.time() - start_time
        
        # Log response
        logger.info(f"Response: {response.status_code} - {process_time:.3f}s")
        
        return response
    except Exception as e:
        process_time = time.time() - start_time
        logger.error(f"Request failed: {str(e)} - {process_time:.3f}s")
        raise

# Error handling middleware
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {str(exc)}", exc_info=True)
    
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "message": "An unexpected error occurred"
        }
    )

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTP exception handler"""
    logger.warning(f"HTTP exception: {exc.status_code} - {exc.detail}")
    
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "status_code": exc.status_code
        }
    )

# Health check endpoint
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "Lumina AI Tutor API"}

# Include routers

app.include_router(auth.router, prefix="/api/auth", tags=["Authentication"])
app.include_router(user.router, prefix="/api/user", tags=["User Management"])
app.include_router(documents.router, prefix="/api/documents", tags=["Document Management"])
app.include_router(narrations.router, prefix="/api/narrations", tags=["Narration Management"])
app.include_router(summary.router, prefix="/api/summary", tags=["Summary Management"])
app.include_router(knowledgetest.router, prefix="/api/knowledgetest", tags=["Knowledge Test Management"])
# app.include_router(streaming.router, prefix="/api", tags=["Streaming"])
app.include_router(chat.router, prefix="/api/chat", tags=["Chat Management"])
app.include_router(notes.router, prefix="/api/notes", tags=["Notes Management"])



import sys
import socket

def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0

if __name__ == "__main__":
    try:
        import uvicorn
        PORT = 8000

        # ✅ Check first before running
        if is_port_in_use(PORT):
            print(f"❌ Port {PORT} is already in use. Please stop the other process first.")
            sys.exit(1)

        print("🚀 Starting Lumina AI Tutor Backend Server...")
        print(f"🌐 Server will be available at: http://0.0.0.0:{PORT}")
        print(f"📚 API Documentation: http://0.0.0.0:{PORT}/docs")
        print(f"🔄 Auto-reload: {'Enabled' if settings.ENVIRONMENT == 'development' else 'Disabled'}")
        
        uvicorn.run(
            "main:app",
            host="0.0.0.0",
            port=PORT,
            reload=True if settings.ENVIRONMENT == "development" else False,
            log_level="info",
            access_log=False
        )

    except ImportError as e:
        print(f"❌ Failed to import uvicorn: {e}")
        print("💡 Make sure uvicorn is installed: pip install uvicorn[standard]")
        raise
