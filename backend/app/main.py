"""Nimbus Brain API.

Checkpoint 1: prove the server starts. Chat and retrieval come later.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="Nimbus Brain")

# The Vite app runs on 5173. Without this, the browser blocks the health request.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok"}
