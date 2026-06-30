"""
Logging configuration for Lumina AI Tutor Backend
"""

import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path

def setup_logging():
    """Setup application logging"""
    
    # Create logs directory if it doesn't exist
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    
    # Configure root logger
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            # Console handler
            logging.StreamHandler(),
            
            # File handler for all logs
            logging.handlers.RotatingFileHandler(
                "logs/app.log",
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            ),
            
            # File handler for errors only
            logging.handlers.RotatingFileHandler(
                "logs/error.log",
                maxBytes=10*1024*1024,  # 10MB
                backupCount=5
            )
        ]
    )
    
    # Set error log handler to only capture ERROR and CRITICAL
    error_handler = logging.handlers.RotatingFileHandler(
        "logs/error.log",
        maxBytes=10*1024*1024,  # 10MB
        backupCount=5
    )
    error_handler.setLevel(logging.ERROR)
    
    # Create formatter
    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    error_handler.setFormatter(formatter)
    
    # Add error handler to root logger
    root_logger = logging.getLogger()
    root_logger.addHandler(error_handler)
    
    # Set specific logger levels
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("watchfiles").setLevel(logging.WARNING)  # Reduce watchfiles noise

def get_logger(name: str) -> logging.Logger:
    """Get logger instance"""
    return logging.getLogger(name)
