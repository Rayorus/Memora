# Memora

Memora is an AI memory assistant that helps Alzheimer's patients remember recent interactions using face recognition, speech transcription, and short conversation summaries.

## Stack

- Frontend: React + Vite
- Backend: FastAPI
- Database/Storage: Supabase
- AI: DeepFace + Whisper + LLM (Anthropic/OpenAI/Groq)

## Quick Start

1. Configure environment files:
    - Root: copy `.env.example` to `.env.local`
    - Frontend: copy `frontend/.env.example` to `frontend/.env.local`
2. Set up Supabase:
    - Run `backend/schema.sql` in Supabase SQL Editor
    - Create public storage bucket `face-images`
3. Run backend:

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8000
```

4. Run frontend:

```bash
cd frontend
npm install
npm run dev
```

## Notes

- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
