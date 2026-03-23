"""
services/supabase_client.py — singleton Supabase client
"""
from supabase import create_client, Client
from config import settings

_client: Client | None = None


def get_supabase() -> Client:
    global _client
    if _client is None:
        if not settings.supabase_url.startswith("http"):
            raise RuntimeError("SUPABASE_URL must be a full https URL")
        if not settings.supabase_service_role_key:
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is missing")
        _client = create_client(
            settings.supabase_url,
            settings.supabase_service_role_key,
        )
    return _client
