"""
config.py — centralised settings loaded from .env / .env.local
All values map directly to the keys defined in .env.local
"""
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(
            str(PROJECT_DIR / ".env.local"),
            str(PROJECT_DIR / ".env"),
            str(BACKEND_DIR / ".env.local"),
            str(BACKEND_DIR / ".env"),
        ),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    supabase_url: str = ""
    supabase_anon_key: str = ""
    supabase_service_role_key: str = ""
    supabase_storage_bucket: str = "face-images"

    # LLM
    llm_provider: str = "anthropic"
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    groq_api_key: str = ""
    grok_api_key: str = ""
    llm_model: str = "claude-3-haiku-20240307"

    # Whisper
    whisper_mode: str = "local"
    whisper_model_size: str = "base"
    openai_whisper_api_key: str = ""
    openai_transcribe_model: str = "gpt-4o-transcribe"
    groq_transcribe_model: str = "whisper-large-v3-turbo"

    # Face recognition
    face_backend: str = "deepface"
    face_model: str = "Facenet512"
    face_similarity_threshold: float = 0.75
    # Min gap between best vs 2nd-best *person* cosine scores; avoids wrong ID when two people tie
    face_match_min_margin: float = 0.05
    # When strict match fails (or after identity split), allow this much lower threshold for patient-only
    # match so the real patient is not auto-registered as Visitor N (same person, two boxes / angles).
    face_patient_recovery_threshold_delta: float = 0.10
    face_distance_threshold: float = 0.55
    face_detector_backend: str = "mediapipe"
    face_min_size: int = 80
    face_min_recognition_size: int = 80
    face_detection_confidence: float = 0.7
    face_nms_iou: float = 0.50
    face_consensus_window: int = 3
    face_consensus_hits: int = 3
    face_recognition_interval: int = 5
    face_max_faces_per_frame: int = 2
    face_detect_resize_width: int = 640
    face_detect_resize_height: int = 360

    # Backend
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    backend_cors_origins: str = "http://localhost:3000"
    secret_key: str = "change-me"
    # Demo only: allow POST /api/admin/reset-all to wipe persons + interactions
    allow_full_database_reset: bool = False

    # Webcam / Audio
    webcam_index: int = 0
    frame_capture_interval: float = 0.5
    audio_sample_rate: int = 16000
    audio_chunk_duration: int = 5
    vad_threshold: float = 0.3

    # Optional features
    enable_emotion_detection: bool = False
    enable_audio_playback: bool = False
    enable_location_tagging: bool = False

    @property
    def cors_origins_list(self) -> List[str]:
        return [o.strip() for o in self.backend_cors_origins.split(",")]


settings = Settings()
