# Lumina AI Tutor Backend

A comprehensive FastAPI backend for the Lumina AI Tutor application, featuring advanced document processing with LangGraph and Gemini 2.5 Pro.

## Features

- **Authentication System**: JWT-based authentication with Supabase integration
- **Document Processing**: AI-powered document analysis using LangGraph workflow
- **Real-time Streaming**: Server-Sent Events for live processing updates
- **Text-to-Speech**: Integrated TTS service for audio generation
- **Database Integration**: Supabase PostgreSQL with proper data modeling

## Architecture


## Installation

1. **Install Dependencies**
   ```bash
   pip install -r requirements.txt
   ```

2. **Install spaCy Model**
   ```bash
   python -m spacy download en_core_web_sm
   ```

3. **Environment Setup**
   ```bash
   cp env.example .env
   # Edit .env with your configuration
   ```

4. **Required Environment Variables**
   ```env
   DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
   SUPABASE_URL=https://your-project.supabase.co
   ANON_KEY=your-supabase-anon-key
   JWT_SECRET=your-jwt-secret
   GOOGLE_API_KEY=your-google-api-key
   ```

## API Endpoints

### Authentication
- `POST /api/auth/signup` - User registration
- `POST /api/auth/login` - User login
- `POST /api/auth/logout` - User logout

### Documents
- `POST /api/documents/` - Upload document
- `GET /api/documents/{id}` - Get document details
- `GET /api/documents/` - Get user documents
- `PUT /api/documents/{id}` - Update document
- `DELETE /api/documents/{id}` - Delete document

### Narrations
- `POST /api/narrations/` - Create narration
- `GET /api/narrations/{id}` - Get narration details
- `GET /api/narrations/document/{document_id}` - Get document narrations
- `PUT /api/narrations/{id}` - Update narration
- `DELETE /api/narrations/{id}` - Delete narration

### Streaming
- `POST /api/streaming/process-document` - Start document processing (SSE)
- `GET /api/streaming/document-status/{id}` - Get processing status

## Document Processing Workflow

### Phase 1: Document Parsing
1. **File Upload**: PDF/DOC files uploaded via multipart form
2. **Text Extraction**: PyMuPDF extracts text with bounding box coordinates
3. **Indexing**: Creates indexed data structure for text segments
4. **Storage**: Saves document metadata to Supabase

### Phase 2: AI Processing
1. **Overview Generation**: Gemini 2.5 Pro creates concise document overview
2. **Chunk Processing**: Document split into logical chunks
3. **Detailed Narration**: AI generates detailed explanations with bounding box references
4. **Context Management**: Maintains context between chunks for coherence

### Phase 3: Streaming & Storage
1. **Real-time Updates**: SSE streams processing progress to frontend
2. **Audio Generation**: TTS service creates audio for narration segments
3. **Database Storage**: Complete narration data saved to Supabase
4. **Status Updates**: Document status updated throughout process
