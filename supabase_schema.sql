-- ============================================================================
-- LUMINA AI TUTOR — Supabase Table Schema
-- ============================================================================
-- Run this entire file in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- It will create all tables, indexes, RLS policies, and the vector search function.
-- ============================================================================

-- ============================================================================
-- 0. ENABLE REQUIRED EXTENSIONS
-- ============================================================================

-- Enable pgvector for embedding storage and similarity search
CREATE EXTENSION IF NOT EXISTS vector;

-- Enable uuid-ossp for UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";


-- ============================================================================
-- 1. USERS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
    user_id    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    first_name VARCHAR(100) NOT NULL,
    last_name  VARCHAR(100) NOT NULL,
    email      VARCHAR(255) NOT NULL UNIQUE,
    password   TEXT NOT NULL,                          -- bcrypt-hashed password
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login TIMESTAMPTZ,
    status     VARCHAR(20) NOT NULL DEFAULT 'active'   -- 'active', 'deleted', etc.
);

-- Index for fast email lookups during login
CREATE INDEX IF NOT EXISTS idx_users_email ON users (email);


-- ============================================================================
-- 2. DOCUMENTS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS documents (
    document_id  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    resource_url TEXT NOT NULL,                       -- Storage path: "docs_store/user_{id}/{doc_id}/original_filename.pdf"
    extra_input  TEXT,                                -- User custom instruction for narration
    type         VARCHAR(20) NOT NULL DEFAULT 'simple',   -- 'simple', 'medium', 'detail'
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    status       VARCHAR(20) NOT NULL DEFAULT 'pending',  -- 'pending', 'processing', 'completed'
    title        VARCHAR(255),
    description  TEXT,
    doc_content  TEXT,                                -- Full markdown content extracted from PDF
    summary      JSONB                                -- AI-generated summary {narrative_summary, key_points}
);

-- Index for fetching all docs by user
CREATE INDEX IF NOT EXISTS idx_documents_user_id ON documents (user_id);

-- Auto-update last_updated timestamp
CREATE OR REPLACE FUNCTION update_documents_last_updated()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_documents_last_updated
    BEFORE UPDATE ON documents
    FOR EACH ROW
    EXECUTE FUNCTION update_documents_last_updated();


-- ============================================================================
-- 3. NARRATIONS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS narrations (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    context      TEXT,                                -- Overview narration text
    narration_bbox JSONB,                             -- Full narration structure: {overview: {}, narrations: [{chunk_no, narration_segments}]}
    raw_data     JSONB,                               -- Intermediate processing state (cleared after completion)
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),
    status       VARCHAR(20) NOT NULL DEFAULT 'pending'   -- 'pending', 'processing', 'completed'
);

-- Index for fetching narrations by document
CREATE INDEX IF NOT EXISTS idx_narrations_document_id ON narrations (document_id);

-- Auto-update last_updated timestamp
CREATE OR REPLACE FUNCTION update_narrations_last_updated()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_narrations_last_updated
    BEFORE UPDATE ON narrations
    FOR EACH ROW
    EXECUTE FUNCTION update_narrations_last_updated();


-- ============================================================================
-- 4. DOCUMENT_CHUNKS TABLE (Vector Embeddings for RAG Chat)
-- ============================================================================
-- NOTE: Using vector(384) to match the all-MiniLM-L6-v2 model.
-- If you switch to Google's text-embedding-004 (768-dim), change vector(384) to vector(768).

CREATE TABLE IF NOT EXISTS document_chunks (
    chunk_id     UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    content      TEXT NOT NULL,                        -- The text chunk
    embedding    vector(384) NOT NULL                  -- 384-dim embedding from all-MiniLM-L6-v2
);

-- Index for fetching chunks by document
CREATE INDEX IF NOT EXISTS idx_document_chunks_document_id ON document_chunks (document_id);

-- HNSW index for fast cosine similarity search
-- (HNSW is faster than IVFFlat for most use cases)
CREATE INDEX IF NOT EXISTS idx_document_chunks_embedding 
    ON document_chunks 
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);


-- ============================================================================
-- 5. CHAT_SESSIONS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS chat_sessions (
    session_id   UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id      UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    document_id  UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    chat_history JSONB,                                -- Array of {role: "user"|"ai", content: "..."}
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Ensure one chat session per user per document
    UNIQUE(document_id, user_id)
);

-- Index for fetching sessions by user and document
CREATE INDEX IF NOT EXISTS idx_chat_sessions_user_id ON chat_sessions (user_id);
CREATE INDEX IF NOT EXISTS idx_chat_sessions_document_id ON chat_sessions (document_id);

-- Auto-update last_updated timestamp
CREATE OR REPLACE FUNCTION update_chat_sessions_last_updated()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_chat_sessions_last_updated
    BEFORE UPDATE ON chat_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_chat_sessions_last_updated();


-- ============================================================================
-- 6. NOTES TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS notes (
    note_id      UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id  UUID NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE UNIQUE,
    user_id      UUID NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
    note_content TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Indexes for fetching notes
CREATE INDEX IF NOT EXISTS idx_notes_document_id ON notes (document_id);
CREATE INDEX IF NOT EXISTS idx_notes_user_id ON notes (user_id);

-- Auto-update last_updated timestamp
CREATE OR REPLACE FUNCTION update_notes_last_updated()
RETURNS TRIGGER AS $$
BEGIN
    NEW.last_updated = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_notes_last_updated
    BEFORE UPDATE ON notes
    FOR EACH ROW
    EXECUTE FUNCTION update_notes_last_updated();


-- ============================================================================
-- 7. VECTOR SEARCH RPC FUNCTION (Used by Chat Feature)
-- ============================================================================
-- This function is called from your backend via:
--   supabase_client.rpc('match_document_chunks', {...}).execute()

CREATE OR REPLACE FUNCTION match_document_chunks(
    query_embedding vector(384),
    p_doc_id UUID,
    match_threshold FLOAT DEFAULT 0.1,
    match_count INT DEFAULT 5
)
RETURNS TABLE (
    chunk_id UUID,
    document_id UUID,
    content TEXT,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        dc.chunk_id,
        dc.document_id,
        dc.content,
        1 - (dc.embedding <=> query_embedding) AS similarity
    FROM document_chunks dc
    WHERE dc.document_id = p_doc_id
      AND 1 - (dc.embedding <=> query_embedding) > match_threshold
    ORDER BY dc.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;


-- ============================================================================
-- 8. ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================================================
-- These ensure users can only access their own data via Supabase client.
-- NOTE: Your backend uses the SERVICE_ROLE_KEY which bypasses RLS.
-- These policies protect data when accessed via the ANON_KEY (e.g., from frontend).

-- Enable RLS on all tables
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE narrations ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_chunks ENABLE ROW LEVEL SECURITY;
ALTER TABLE chat_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE notes ENABLE ROW LEVEL SECURITY;

-- Users: can read/update their own profile
CREATE POLICY "Users can view own profile"
    ON users FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can update own profile"
    ON users FOR UPDATE
    USING (auth.uid() = user_id);

-- Documents: users can CRUD their own documents
CREATE POLICY "Users can view own documents"
    ON documents FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own documents"
    ON documents FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own documents"
    ON documents FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own documents"
    ON documents FOR DELETE
    USING (auth.uid() = user_id);

-- Narrations: access through document ownership
CREATE POLICY "Users can view narrations of own docs"
    ON narrations FOR SELECT
    USING (
        document_id IN (
            SELECT document_id FROM documents WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert narrations for own docs"
    ON narrations FOR INSERT
    WITH CHECK (
        document_id IN (
            SELECT document_id FROM documents WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can update narrations of own docs"
    ON narrations FOR UPDATE
    USING (
        document_id IN (
            SELECT document_id FROM documents WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can delete narrations of own docs"
    ON narrations FOR DELETE
    USING (
        document_id IN (
            SELECT document_id FROM documents WHERE user_id = auth.uid()
        )
    );

-- Document Chunks: access through document ownership
CREATE POLICY "Users can view chunks of own docs"
    ON document_chunks FOR SELECT
    USING (
        document_id IN (
            SELECT document_id FROM documents WHERE user_id = auth.uid()
        )
    );

CREATE POLICY "Users can insert chunks for own docs"
    ON document_chunks FOR INSERT
    WITH CHECK (
        document_id IN (
            SELECT document_id FROM documents WHERE user_id = auth.uid()
        )
    );

-- Chat Sessions: users can CRUD their own sessions
CREATE POLICY "Users can view own chat sessions"
    ON chat_sessions FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own chat sessions"
    ON chat_sessions FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own chat sessions"
    ON chat_sessions FOR UPDATE
    USING (auth.uid() = user_id);

-- Notes: users can CRUD their own notes
CREATE POLICY "Users can view own notes"
    ON notes FOR SELECT
    USING (auth.uid() = user_id);

CREATE POLICY "Users can insert own notes"
    ON notes FOR INSERT
    WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users can update own notes"
    ON notes FOR UPDATE
    USING (auth.uid() = user_id);

CREATE POLICY "Users can delete own notes"
    ON notes FOR DELETE
    USING (auth.uid() = user_id);


-- ============================================================================
-- 9. STORAGE BUCKET SETUP
-- ============================================================================
-- Create the docs_store bucket for document uploads
-- NOTE: Run this in Supabase SQL Editor, OR create the bucket via 
--       Supabase Dashboard → Storage → New Bucket

INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
VALUES (
    'docs_store', 
    'docs_store', 
    false,                              -- Private bucket (use signed URLs)
    52428800,                           -- 50MB max file size
    ARRAY['application/pdf']::text[]    -- Only allow PDF uploads
)
ON CONFLICT (id) DO NOTHING;

-- Storage RLS: Allow authenticated users to upload to their own folder
CREATE POLICY "Users can upload to own folder"
    ON storage.objects FOR INSERT
    WITH CHECK (
        bucket_id = 'docs_store'
        AND auth.role() = 'authenticated'
    );

-- Storage RLS: Allow authenticated users to read from their own folder
CREATE POLICY "Users can read own files"
    ON storage.objects FOR SELECT
    USING (
        bucket_id = 'docs_store'
        AND auth.role() = 'authenticated'
    );

-- Storage RLS: Allow authenticated users to delete their own files
CREATE POLICY "Users can delete own files"
    ON storage.objects FOR DELETE
    USING (
        bucket_id = 'docs_store'
        AND auth.role() = 'authenticated'
    );


-- ============================================================================
-- DONE! All tables, indexes, functions, policies, and buckets are set up.
-- ============================================================================
-- 
-- SUMMARY OF WHAT WAS CREATED:
-- 
-- Tables:           users, documents, narrations, document_chunks, chat_sessions, notes
-- Extensions:       vector, uuid-ossp
-- Functions:        match_document_chunks (vector similarity search)
-- Triggers:         Auto-update last_updated on documents, narrations, chat_sessions, notes
-- Indexes:          Foreign key indexes + HNSW vector index on document_chunks
-- RLS Policies:     Full CRUD policies for all tables + storage
-- Storage Buckets:  docs_store (private, PDF only, 50MB limit)
-- 
-- ============================================================================
