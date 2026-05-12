-- ============================================================
--  MEMORA — Supabase Database Schema
--  Run this in Supabase SQL Editor to initialise the database.
-- ============================================================

-- Enable UUID extension
create extension if not exists "pgcrypto";

-- ── persons ──────────────────────────────────────────────────
create table if not exists persons (
  id             uuid primary key default gen_random_uuid(),
  name           text,
  role           text not null check (role in ('patient', 'person')) default 'person',
  face_embedding json not null,
  created_at     timestamptz not null default now()
);

-- ── interactions ─────────────────────────────────────────────
create table if not exists interactions (
  id         uuid primary key default gen_random_uuid(),
  person_id  uuid not null references persons (id) on delete cascade,
  summary    text not null,
  transcript text,
  image_url  text,
  timestamp  timestamptz not null default now()
);

create index if not exists idx_interactions_person_id on interactions (person_id);
create index if not exists idx_interactions_timestamp  on interactions (timestamp desc);

-- ── Row Level Security (optional, enable as needed) ──────────
-- alter table persons      enable row level security;
-- alter table interactions enable row level security;

-- ── Storage bucket (run via dashboard or API, not SQL) ───────
-- Bucket name : face-images
-- Public access: true  (or use signed URLs for privacy)
