# Goal
Create a transcription service. MVP. 
User uploads a small German audio or video file, the service transcribes it and returns the transcript as JSON or TXT. 
The service should be able to be dockerized and run on Mac or windows. 
Optionally: there should be a second service to be able to summarize the transcription. Using ollama and some lightweight llm. 
Optionally and done in the next steps but considered during design.

# Design
FastAPI with Swagger UI as the frontend. In later work the frontend can be more user friendly. Uvicorn as server. 
Endpoints for transcription, by default now summariziation off, later by default on, can be changed by a parameter. 
Later: separate endpoint for summarization. The work should be operated using queues and sql db. 
Sqlite is ok to start with. There should be a table for tasks and outbox patterns so that a separate thread could read 
the table and put the tasks into the queue for workers to pick up. We can start with one worker that does the transcription 
using the whisper model, the small one (no more than 20 sec audios or videos are expected), we start small). 
The queue can be simply implemented using in-memroy queue.Queue. 