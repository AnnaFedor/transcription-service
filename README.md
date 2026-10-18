# transcription-service

MVP service that transcribes short German audio/video files (≤ 20 s) with Whisper (small) and returns the transcript as JSON or TXT.

- **API:** FastAPI + Uvicorn, Swagger UI as frontend
- **Processing:** SQLite task table + outbox → in-memory queue → worker
- **Runs:** Docker on Mac and Windows
- **Later:** optional summarization via Ollama with a lightweight LLM
