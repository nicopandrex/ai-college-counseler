"""Web API (M9): upload a DegreeWorks audit, then plan the term by chatting.

Sessions live in memory: this is for local testing, one process, no accounts. The uploaded
PDF is written to a temporary file only while it is read, then deleted. Every reply and view
comes from ChatSession, so the web shows exactly what the CLI shows.
"""

from __future__ import annotations

import os
import secrets
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from planner_chat.session import ChatSession
from planner_ingest.chat_setup import open_chat, read_audit

MAX_PDF_BYTES = 20 * 1024 * 1024
Opener = Callable[[Path], ChatSession]  # audit PDF on disk -> a ready chat session


def open_from_pdf(pdf: Path) -> ChatSession:
    """Real audits: extraction (LLM, cached) + UVM term data. Each session gets its own
    gateway, so LLM_MAX_LIVE_CALLS caps paid calls per session."""
    return open_chat(read_audit(pdf), term_code=os.environ.get("PLANNER_TERM", "2027SP"))


class Message(BaseModel):
    text: str = Field(min_length=1, max_length=2000)


class _Live:
    def __init__(self, chat: ChatSession) -> None:
        self.chat = chat
        self.lock = threading.Lock()  # one turn at a time per session


def create_app(opener: Opener = open_from_pdf) -> FastAPI:
    app = FastAPI(title="degree-planner")
    sessions: dict[str, _Live] = {}

    def live(session_id: str) -> _Live:
        found = sessions.get(session_id)
        if found is None:
            raise HTTPException(404, "That session has ended. Upload your audit again.")
        return found

    def turn(session_id: str, act: Callable[[ChatSession], str]) -> dict[str, Any]:
        session = live(session_id)
        with session.lock:
            reply = act(session.chat)
            return {"reply": reply, "view": session.chat.view()}

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/sessions")
    async def upload(request: Request) -> dict[str, Any]:
        body = await request.body()
        if len(body) > MAX_PDF_BYTES:
            raise HTTPException(413, "That file is too big for an audit PDF.")
        if not body.startswith(b"%PDF"):
            raise HTTPException(400, "Please upload your DegreeWorks audit as a PDF.")
        with tempfile.TemporaryDirectory() as folder:
            pdf = Path(folder) / "audit.pdf"
            pdf.write_bytes(body)
            try:
                chat = await run_in_threadpool(opener, pdf)
            except Exception as exc:  # shown to the student; the audit itself isn't logged
                raise HTTPException(422, f"I couldn't read that audit ({exc}).") from exc
        chat.list_schedules = False  # the canvas draws them
        session_id = secrets.token_urlsafe(16)
        sessions[session_id] = _Live(chat)
        return {"id": session_id, "reply": chat.welcome(), "view": chat.view()}

    @app.get("/api/sessions/{session_id}")
    def view(session_id: str) -> dict[str, Any]:
        return live(session_id).chat.view()

    @app.post("/api/sessions/{session_id}/messages")
    def message(session_id: str, body: Message) -> dict[str, Any]:
        return turn(session_id, lambda chat: chat.handle(body.text))

    @app.delete("/api/sessions/{session_id}/rules/{rule_id}")
    def drop(session_id: str, rule_id: str) -> dict[str, Any]:
        return turn(session_id, lambda chat: chat.drop(rule_id))

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")))
