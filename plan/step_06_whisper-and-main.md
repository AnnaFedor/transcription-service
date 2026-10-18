# Step 6 — FasterWhisperTranscriber and main.py wiring

## Goal

Plug in the real model and make the service runnable: implement `FasterWhisperTranscriber`, replace the PyCharm stub
`main.py` with the composition root that loads the model, starts the relay and worker threads, runs uvicorn and shuts
down cleanly. Verify locally in Swagger UI with a real German clip.

## Prerequisites

- Step 5 done (pipeline works with `FakeTranscriber`).
- Internet access for the first model download (~460 MB for `small`, cached in the Hugging Face cache or
  `WHISPER_DOWNLOAD_ROOT`).
- A German test clip: generated with the macOS voice "Anna" (verified installed), e.g.
  `say -v Anna -o data/sample.aiff "Guten Tag. Dies ist ein kurzer Test des Transkriptionsdienstes."`

## Tests (written first)

No automated tests in this step. Test scope is limited to the four agreed test groups (see
[plan_overview.md](plan_overview.md) → Steps); the real model is never used in automated tests. The existing
tests from steps 2, 4 and 5 must stay green (`uv run pytest`).

The real model and the wiring are verified manually (see the checklist at the end of Implementation details).

## Implementation details

`app/transcriber.py`:
- `class FasterWhisperTranscriber(model_name, device, compute_type, download_root=None)`:
  - `__init__` creates `WhisperModel(model_name, device=device, compute_type=compute_type, download_root=...)` — the
    load happens here so a broken setup fails at startup.
  - `transcribe(path, language)`: `segments, info = model.transcribe(str(path), language=language, beam_size=5)`;
    materialise `list(segments)` (it is a lazy generator — transcription only runs while iterating); build
    `TranscriptionResult(text=" ".join(s.text.strip() ...), segments=[Segment(s.start, s.end, s.text.strip())],
    language=info.language, duration=info.duration)`.

`main.py` (replaces the PyCharm stub):
- `@dataclass class Components(app, repository, storage, queue, relay, worker, stop_event)`.
- `build_components(settings, transcriber) -> Components` — creates repository (`init_schema()`), storage, queue,
  stop event, relay, worker and `create_app(settings, repository, storage)`.
- `start_background(components) -> list[Thread]` — `Thread(target=relay.run, name="outbox-relay", daemon=True)`
  and `Thread(target=worker.run, name="transcription-worker", daemon=True)`, started.
- `stop_background(components, threads, timeout=30)` — `stop_event.set()`, `join(timeout)` each; the worker
  finishes the task in progress first.
- `main()`:
  1. `logging.basicConfig(level=INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")`.
  2. `settings = Settings()`; create `data_dir`.
  3. Load `FasterWhisperTranscriber` from settings, log model name and load time.
  4. `components = build_components(...)`; `threads = start_background(components)`.
  5. `try: uvicorn.run(components.app, host=settings.host, port=settings.port) finally: stop_background(...)`.
     `uvicorn.run` handles SIGINT/SIGTERM and returns, then the threads are stopped.
- `if __name__ == "__main__": main()`.

Manual verification checklist (differences recorded under Deviations):
1. `uv run python main.py` → log shows model loaded, threads started, Uvicorn on `http://127.0.0.1:8000`.
2. Open `http://127.0.0.1:8000/docs`, upload `data/sample.aiff` → `202`.
3. Poll status → `done` within ~15 s; result JSON and TXT contain the spoken sentence; detected language `de`.
4. Upload the same clip with `language=auto` → `done`, `language` is `de`.
5. Status and result for an unknown id → `404`; result for a task still `pending`/`processing` → `409`.
6. Upload a > 20 s clip → `422`; upload a text file → `422`.
7. Ctrl-C → clean shutdown log, no traceback.
- Commit: `Add faster-whisper transcriber and main entrypoint`.

## Deliverables

| Artifact | Description |
|---|---|
| `app/transcriber.py` | `FasterWhisperTranscriber` added |
| `main.py` | Composition root: `Components`, `build_components`, `start_background`, `stop_background`, `main` |

## References

### Internal

- [plan_overview.md](plan_overview.md) — Architecture, Decisions (#2, #3, #4, #5, #19)
- [docs/design-decisions.md](../docs/design-decisions.md) — Architecture, Model & runtime
- [step_05_queue-relay-worker.md](step_05_queue-relay-worker.md) — `Transcriber` protocol, relay, worker

### External

- faster-whisper: https://github.com/SYSTRAN/faster-whisper
- Uvicorn programmatic usage: https://www.uvicorn.org/deployment/#running-programmatically
- macOS `say`: `man say`

## Deviations from plan

