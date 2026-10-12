"""Learning from feedback: 👎 + comment become proposals; nothing changes until a curator approves."""
import json

from app import db, indicators
from app.config import ROOT
from app.models import check_indicator
from app.security import clean_text


def submit(thread_id: str, rating: int, question: str, answer: str, comment: str = "",
           phrase: str = "", code: str = "") -> list[int]:
    """Store feedback; on 👎 propose an eval case and, if a correct indicator was given, an alias."""
    comment, question = clean_text(comment, 2000), clean_text(question, 1000)
    db.add_feedback(thread_id, rating, comment, answer)
    proposal_ids = []
    if rating < 0:
        proposal_ids.append(db.add_proposal("eval_case", {"question": question, "bad_answer": answer[:2000],
                                                  "comment": comment}))
        if phrase.strip() and code.strip():
            code = check_indicator(code.strip())
            if not any(indicator["id"] == code for indicator in indicators._catalog()):
                raise ValueError(f"{code} is not in the World Bank catalog")
            proposal_ids.append(db.add_proposal("alias", {"phrase": clean_text(phrase, 80).lower(), "code": code,
                                                 "question": question, "comment": comment}))
    return proposal_ids


def approve(proposal_id: int) -> dict:
    proposal = db.decide_proposal(proposal_id, "approved")
    if proposal["kind"] == "alias":
        db.upsert_alias(proposal["payload"]["phrase"], proposal["payload"]["code"])
    elif proposal["kind"] == "eval_case":  # a curator turns candidates into golden cases with expectations
        path = ROOT / "evals" / "candidates.jsonl"
        path.parent.mkdir(exist_ok=True)
        with path.open("a") as candidates_file:
            candidates_file.write(json.dumps({"id": f"feedback-{proposal_id}", **proposal["payload"]}) + "\n")
    return proposal


def reject(proposal_id: int) -> dict:
    return db.decide_proposal(proposal_id, "rejected")
