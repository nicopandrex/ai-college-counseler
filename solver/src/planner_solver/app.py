"""FastAPI entrypoint for the solver service."""

from fastapi import FastAPI

app = FastAPI(title="degree-planner-solver")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
