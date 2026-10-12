"""JSON API on NiceGUI's FastAPI app, plus security middleware."""
from fastapi import HTTPException
from nicegui import app
from pydantic import BaseModel, Field

from app import db, openai_compat, scoring, snapshot
from app.models import ISO3
from app.security import OriginCheckMiddleware, SecurityHeadersMiddleware

app.add_middleware(OriginCheckMiddleware)
app.add_middleware(SecurityHeadersMiddleware)


@app.get("/api/scores")
def api_scores():
    scores = scoring.all_scores()
    return {
        "snapshot": snapshot.snapshot_id(),
        "scores": [
            {"iso3": iso3, "score": int(row["score"]), "rank": int(row["rank"])} for iso3, row in scores.iterrows()
        ],
    }


@app.get("/api/country/{iso3}")
def api_country(iso3: str):
    if not ISO3.fullmatch(iso3):
        raise HTTPException(400, "Invalid ISO3 code")
    return scoring.explain(iso3, scoring.all_scores())


class Feedback(BaseModel):
    thread_id: str = Field(max_length=64)
    rating: int = Field(ge=-1, le=1)
    comment: str = Field("", max_length=2000)
    answer: str = Field("", max_length=4000)


@app.post("/api/feedback")
def api_feedback(feedback: Feedback):
    db.add_feedback(feedback.thread_id, feedback.rating, feedback.comment, feedback.answer)
    return {"ok": True}


app.include_router(openai_compat.router, prefix="/v1")
