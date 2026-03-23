-- Run in Supabase SQL editor so solo-patient memories filter correctly.
-- Optional: app works without it (falls back to latest any interaction).

alter table public.interactions
  add column if not exists patient_solo boolean not null default false;

create index if not exists interactions_person_solo_idx
  on public.interactions (person_id, patient_solo, timestamp desc);
