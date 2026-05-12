"""
services/llm_service.py — conversation summarization via configured LLM provider
"""
from config import settings
import re

_SYSTEM_PROMPT = (
    "You are a concise assistant. Summarize the following conversation transcript "
    "in one short phrase (5-10 words) that captures the main topic or intent. "
    "Reply with ONLY the summary phrase, no punctuation at the end, no preamble."
)


def _summarize_local(transcript: str) -> str:
    """A free local fallback summarizer when no cloud LLM should be used."""
    clean = re.sub(r"\s+", " ", transcript or "").strip()
    if not clean:
        return "Brief conversation"

    # Keep a short phrase feel (roughly 5-10 words) without external model calls.
    words = re.findall(r"[A-Za-z0-9']+", clean)
    if not words:
        return "Brief conversation"

    phrase = " ".join(words[:10])
    if len(words) > 10:
        phrase += "..."
    return phrase


def summarize(transcript: str) -> str:
    provider = settings.llm_provider.lower()

    if provider in {"local", "none", "offline"}:
        return _summarize_local(transcript)

    if provider == "anthropic":
        import anthropic
        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        message = client.messages.create(
            model=settings.llm_model,
            max_tokens=64,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": transcript}],
        )
        return message.content[0].text.strip()

    elif provider == "openai":
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            max_tokens=64,
        )
        return resp.choices[0].message.content.strip()

    elif provider == "groq":
        from groq import Groq
        client = Groq(api_key=settings.groq_api_key)
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            max_tokens=64,
        )
        return resp.choices[0].message.content.strip()

    elif provider == "grok":
        from openai import OpenAI

        client = OpenAI(
            api_key=settings.grok_api_key,
            base_url="https://api.x.ai/v1",
        )
        resp = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": transcript},
            ],
            max_tokens=64,
        )
        return resp.choices[0].message.content.strip()

    else:
        return _summarize_local(transcript)
