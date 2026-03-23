"""
services/stt_service.py — Speech-to-text using Whisper (local or API)
"""
import io
import tempfile
from config import settings


_WHISPER_MODEL = None


def _is_real_openai_key(value: str | None) -> bool:
    if not value:
        return False
    v = value.strip()
    if not v:
        return False
    lower_v = v.lower()
    placeholders = (
        "your-openai-api-key",
        "your-openai-key",
        "your_api_key",
        "replace-with",
        "changeme",
    )
    if any(p in lower_v for p in placeholders):
        return False
    return v.startswith("sk-")


def _get_openai_key() -> str | None:
    if _is_real_openai_key(settings.openai_whisper_api_key):
        return settings.openai_whisper_api_key
    if _is_real_openai_key(settings.openai_api_key):
        return settings.openai_api_key
    return None


def _get_groq_key() -> str | None:
    # Accept either GROQ_API_KEY (preferred) or GROK_API_KEY if it contains a Groq-style key.
    if _is_real_openai_key(settings.groq_api_key) or (settings.groq_api_key and settings.groq_api_key.strip().startswith("gsk_")):
        return settings.groq_api_key.strip()
    if settings.grok_api_key and settings.grok_api_key.strip().startswith("gsk_"):
        return settings.grok_api_key.strip()
    return None


def _audio_suffix(filename: str | None, content_type: str | None) -> str:
    if filename and "." in filename:
        ext = filename[filename.rfind("."):].lower()
        if ext in {".wav", ".mp3", ".m4a", ".mp4", ".webm", ".ogg", ".flac", ".opus"}:
            return ext
    if content_type:
        ctype = content_type.lower()
        if "webm" in ctype:
            return ".webm"
        if "wav" in ctype:
            return ".wav"
        if "ogg" in ctype:
            return ".ogg"
        if "mpeg" in ctype or "mp3" in ctype:
            return ".mp3"
        if "mp4" in ctype:
            return ".mp4"
        if "m4a" in ctype:
            return ".m4a"
        if "opus" in ctype:
            return ".opus"
    return ".webm"


def transcribe_audio(audio_bytes: bytes, filename: str | None = None, content_type: str | None = None) -> str:
    """Transcribe uploaded audio bytes to text."""
    suffix = _audio_suffix(filename, content_type)
    if settings.whisper_mode == "local":
        try:
            return _transcribe_local(audio_bytes, suffix)
        except Exception as local_error:
            local_msg = str(local_error).lower()
            if "ffmpeg" in local_msg:
                raise RuntimeError(
                    "Local Whisper needs ffmpeg. Install ffmpeg or switch WHISPER_MODE=openai-api with active OpenAI billing."
                ) from local_error
            raise RuntimeError(
                f"Local Whisper failed: {local_error}. Check ffmpeg installation and audio input format."
            ) from local_error

    if settings.whisper_mode == "groq-api":
        groq_key = _get_groq_key()
        if not groq_key:
            raise RuntimeError("GROQ_API_KEY is missing or invalid for whisper_mode=groq-api")
        return _transcribe_groq(audio_bytes, groq_key, suffix)

    api_key = _get_openai_key()
    if not api_key:
        raise RuntimeError("OPENAI_WHISPER_API_KEY/OPENAI_API_KEY is missing or invalid for whisper_mode=openai-api")
    return _transcribe_api(audio_bytes, api_key, suffix)


def _transcribe_local(audio_bytes: bytes, suffix: str) -> str:
    global _WHISPER_MODEL
    import whisper

    if _WHISPER_MODEL is None:
        _WHISPER_MODEL = whisper.load_model(settings.whisper_model_size)

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name
    try:
        result = _WHISPER_MODEL.transcribe(tmp_path)
    except FileNotFoundError as e:
        if "ffmpeg" in str(e).lower():
            raise RuntimeError("ffmpeg is required for local transcription. Install ffmpeg and restart backend.") from e
        raise
    return result["text"].strip()


def _transcribe_api(audio_bytes: bytes, api_key: str, suffix: str) -> str:
    from openai import OpenAI
    client = OpenAI(api_key=api_key)
    buf = io.BytesIO(audio_bytes)
    buf.name = f"audio{suffix}"
    try:
        transcript = client.audio.transcriptions.create(model=settings.openai_transcribe_model, file=buf)
        return transcript.text.strip()
    except Exception as e:
        msg = str(e)
        if "model" in msg.lower() and "does not exist" in msg.lower():
            transcript = client.audio.transcriptions.create(model="whisper-1", file=buf)
            return transcript.text.strip()
        if "insufficient_quota" in msg or "exceeded your current quota" in msg.lower():
            raise RuntimeError(
                "OpenAI quota exceeded. Add billing/credits, or use WHISPER_MODE=local with ffmpeg installed."
            ) from e
        raise


def _transcribe_groq(audio_bytes: bytes, api_key: str, suffix: str) -> str:
    from groq import Groq

    client = Groq(api_key=api_key)
    buf = io.BytesIO(audio_bytes)
    buf.name = f"audio{suffix}"
    transcript = client.audio.transcriptions.create(
        model=settings.groq_transcribe_model,
        file=buf,
    )
    return (transcript.text or "").strip()
