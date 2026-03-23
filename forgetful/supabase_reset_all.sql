-- Optional: wipe all demo data in Supabase SQL Editor.
-- Or use the in-app “Clear database & start over” (needs ALLOW_FULL_DATABASE_RESET=true).

truncate table public.interactions, public.persons restart identity;

-- Note: Storage bucket `face-images` is not cleared; remove files in Dashboard if needed.
