-- Initial PostgreSQL schema for the Omiryn MVP.
-- Extensions:
--   CREATE EXTENSION IF NOT EXISTS vector;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE,
    email TEXT UNIQUE,
    display_name TEXT,
    date_of_birth DATE,
    gender TEXT,
    city TEXT,
    country TEXT,
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    account_status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT users_contact_required CHECK (phone IS NOT NULL OR email IS NOT NULL)
);

CREATE TABLE user_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    bio TEXT,
    education TEXT,
    profession TEXT,
    religion TEXT,
    community TEXT,
    languages TEXT[] NOT NULL DEFAULT '{}',
    relationship_intent TEXT,
    min_age_preference INTEGER,
    max_age_preference INTEGER,
    location_radius_km INTEGER,
    visibility_status TEXT NOT NULL DEFAULT 'private',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    conversation_type TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE agent_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES agent_conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    safety_status TEXT NOT NULL DEFAULT 'unchecked',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE structured_dating_profiles (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    source_conversation_id UUID REFERENCES agent_conversations(id) ON DELETE SET NULL,
    relationship_intent TEXT,
    values_json JSONB NOT NULL DEFAULT '[]',
    lifestyle_json JSONB NOT NULL DEFAULT '{}',
    communication_style_json JSONB NOT NULL DEFAULT '{}',
    family_expectations_json JSONB NOT NULL DEFAULT '{}',
    children_preference TEXT,
    relocation_preference TEXT,
    dealbreakers_json JSONB NOT NULL DEFAULT '[]',
    soft_preferences_json JSONB NOT NULL DEFAULT '{}',
    green_flags_json JSONB NOT NULL DEFAULT '[]',
    red_flags_json JSONB NOT NULL DEFAULT '[]',
    confidence_json JSONB NOT NULL DEFAULT '{}',
    extraction_version TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE profile_embeddings (
    user_id UUID PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    embedding_model TEXT NOT NULL,
    -- Enable pgvector and uncomment once vector dimensions are chosen.
    -- embedding vector(1536) NOT NULL,
    embedding_placeholder JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE match_candidates (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_a_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    user_b_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    compatibility_score NUMERIC(5, 2) NOT NULL,
    status TEXT NOT NULL DEFAULT 'suggested',
    explanation TEXT,
    possible_frictions TEXT,
    score_breakdown_json JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT match_candidate_distinct_users CHECK (user_a_id <> user_b_id)
);

CREATE TABLE match_decisions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_candidate_id UUID NOT NULL REFERENCES match_candidates(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    decision TEXT NOT NULL,
    reason TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT match_decision_unique UNIQUE (match_candidate_id, user_id)
);

CREATE TABLE human_chats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_candidate_id UUID NOT NULL UNIQUE REFERENCES match_candidates(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE human_chat_messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    chat_id UUID NOT NULL REFERENCES human_chats(id) ON DELETE CASCADE,
    sender_user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    moderation_status TEXT NOT NULL DEFAULT 'unchecked',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE match_feedback (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    match_candidate_id UUID NOT NULL REFERENCES match_candidates(id) ON DELETE CASCADE,
    user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    rating INTEGER CHECK (rating BETWEEN 1 AND 5),
    outcome TEXT,
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_users_city_country ON users(city, country);
CREATE INDEX idx_agent_conversations_user_id ON agent_conversations(user_id);
CREATE INDEX idx_agent_messages_conversation_id ON agent_messages(conversation_id);
CREATE INDEX idx_match_candidates_user_a ON match_candidates(user_a_id);
CREATE INDEX idx_match_candidates_user_b ON match_candidates(user_b_id);
CREATE UNIQUE INDEX idx_match_candidates_unique_unordered_pair
    ON match_candidates (LEAST(user_a_id, user_b_id), GREATEST(user_a_id, user_b_id));
