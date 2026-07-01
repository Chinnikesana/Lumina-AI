"""
SQLAlchemy models and Pydantic schemas
"""

import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List
from sqlalchemy import Column, String, DateTime, Text, ForeignKey, Enum
from sqlalchemy.dialects.postgresql import UUID, JSONB
from pgvector.sqlalchemy import Vector
from sqlalchemy.orm import relationship
from pydantic import BaseModel, EmailStr, Field
import enum

from ..core.database import Base 

# Enums
class DocumentType(str, enum.Enum):
    SIMPLE = "simple"
    MEDIUM = "medium"
    DETAIL = "detail"

class DocumentStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"

class NarrationStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"

# SQLAlchemy Models
class User(Base):
    """User model"""
    __tablename__ = "users"
    
    user_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password = Column(Text, nullable=False)  # Hashed password
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)
    status = Column(String(20), default="active", nullable=False)

class Document(Base):
    """Document model"""
    __tablename__ = "documents"
    
    document_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    resource_url = Column(Text, nullable=False)  # PDF/DOC file URL from Supabase storage
    extra_input = Column(Text, nullable=True)  # User custom instruction
    type = Column(Enum(DocumentType), default=DocumentType.SIMPLE, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(Enum(DocumentStatus), default=DocumentStatus.PENDING, nullable=False)
    title = Column(String(255), nullable=True)
    description = Column(Text, nullable=True)
    doc_content = Column(Text, nullable=True)
    summary = Column(Text, nullable=True)
    
    
    # Relationships
    user = relationship("User", back_populates="documents")
    narrations = relationship("Narration", back_populates="document", cascade="all, delete-orphan")

class Chat_Sessions(Base):
    """Chat Sessions model"""
    __tablename__ = "chat_sessions"
    
    session_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.document_id', ondelete='CASCADE'), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    chat_history= Column(JSONB, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)


class Document_Chunks(Base):
    """Document Chunks model"""
    __tablename__ = "document_chunks"
    
    chunk_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.document_id', ondelete='CASCADE'), nullable=False, index=True)
    content= Column(Text, nullable=False)
    embedding= Column(Vector(384), nullable=False)  

class Notes(Base):
    """Notes model"""
    __tablename__ = "notes"
    
    note_id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.document_id', ondelete='CASCADE'), nullable=False, index=True, unique=True)
    user_id = Column(UUID(as_uuid=True), ForeignKey('users.user_id', ondelete='CASCADE'), nullable=False, index=True)
    note_content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)




class Narration(Base):
    """Narration model"""
    __tablename__ = "narrations"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4, index=True)
    document_id = Column(UUID(as_uuid=True), ForeignKey('documents.document_id', ondelete='CASCADE'), nullable=False, index=True)
    context = Column(Text, nullable=True)  # Overview narration
    narration_bbox = Column(JSONB, nullable=True)  # Page narration + bbox highlights in JSON format
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)
    status = Column(Enum(NarrationStatus), default=NarrationStatus.PENDING, nullable=False)
    
    # Relationships
    document = relationship("Document", back_populates="narrations")

# Add relationship to User model
User.documents = relationship("Document", back_populates="user", cascade="all, delete-orphan")

# Pydantic Schemas
class UserBase(BaseModel):
    """Base user schema"""
    first_name: str = Field(..., min_length=1, max_length=100)
    last_name: str = Field(..., min_length=1, max_length=100)
    email: EmailStr

class UserCreate(UserBase):
    """Schema for user creation"""
    password: str = Field(..., min_length=6, max_length=72)

class UserUpdate(BaseModel):
    """Schema for user updates"""
    first_name: Optional[str] = Field(None, min_length=1, max_length=100)
    last_name: Optional[str] = Field(None, min_length=1, max_length=100)
    email: Optional[EmailStr] = None

class UserResponse(UserBase):
    """Schema for user responses"""
    user_id: uuid.UUID
    created_at: datetime
    last_login: Optional[datetime] = None
    status: str
    
    class Config:
        from_attributes = True

class UserLogin(BaseModel):
    """Schema for user login"""
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    """Schema for token response"""
    access_token: str
    token_type: str
    user_id: uuid.UUID
    first_name: str
    last_name: str
    email: str

class TokenData(BaseModel):
    """Schema for token data"""
    user_id: Optional[str] = None

# Document Schemas
class DocumentBase(BaseModel):
    """Base document schema"""
    resource_url: str
    extra_input: Optional[str] = None
    type: DocumentType = DocumentType.SIMPLE

class DocumentCreate(DocumentBase):
    """Schema for document creation"""
    pass

class DocumentUpdate(BaseModel):
    """Schema for document updates"""
    extra_input: Optional[str] = None
    type: Optional[DocumentType] = None
    status: Optional[DocumentStatus] = None

class DocumentResponse(DocumentBase):
    """Schema for document responses"""
    id: uuid.UUID
    user_id: uuid.UUID
    created_at: datetime
    last_updated: datetime
    status: DocumentStatus
    # Optional extras returned by GET /documents/{id}
    title: Optional[str] = None
    description: Optional[str] = None
    narration: Optional[Dict[str, Any]] = None
    
    class Config:
        from_attributes = True

# Narration Schemas
class NarrationSegment(BaseModel):
    """Schema for individual narration segment"""
    transcript_id: str
    transcript_text: str
    highlight_bounding_box_ids: List[str]
    scroll_to_bounding_box_id: str
    estimated_duration_ms: int

class NarrationChunk(BaseModel):
    """Schema for narration chunk"""
    chunk_no: int
    segments: List[NarrationSegment]
    context_summary_for_next_chunk: str

class NarrationBboxData(BaseModel):
    """Schema for narration bbox data structure"""
    overview: Optional[Dict[str, Any]] = None
    narrations: List[NarrationChunk] = []

class NarrationBase(BaseModel):
    """Base narration schema"""
    context: Optional[str] = None
    narration_bbox: Optional[NarrationBboxData] = None

class NarrationCreate(NarrationBase):
    """Schema for narration creation"""
    document_id: uuid.UUID

class NarrationUpdate(BaseModel):
    """Schema for narration updates"""
    context: Optional[str] = None
    narration_bbox: Optional[NarrationBboxData] = None
    status: Optional[NarrationStatus] = None

class NarrationResponse(NarrationBase):
    """Schema for narration responses"""
    id: uuid.UUID
    document_id: uuid.UUID
    created_at: datetime
    last_updated: datetime
    status: NarrationStatus
    
    class Config:
        from_attributes = True



