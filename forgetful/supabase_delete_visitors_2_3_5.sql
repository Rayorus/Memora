-- Delete auto-registered visitors named Visitor 2, 3, or 5 (spacing/case tolerant).
-- Run in Supabase → SQL Editor. Interactions for these persons cascade-delete.

DELETE FROM persons
WHERE role = 'person'
  AND name ~* '^\s*visitor\s*(2|3|5)\s*$';

-- Optional: see what was removed (run before DELETE if you want to preview):
-- SELECT id, name, role, created_at FROM persons
-- WHERE role = 'person' AND name ~* '^\s*visitor\s*(2|3|5)\s*$';
