"""Learning from 👎 feedback: proposals, curator approval, learned aliases."""
import pytest

from app import db, feedback, indicators


def test_thumbs_down_alias_needs_approval_then_is_used(data_dir, monkeypatch):
    monkeypatch.setattr(feedback, "ROOT", data_dir)
    proposal_ids = feedback.submit("t1", -1, "rural power in India?", "answer", "wrong indicator",
                          phrase="rural power", code="EG.ELC.ACCS.RU.ZS")
    assert len(proposal_ids) == 2  # eval case + alias
    assert indicators.search("rural power")[0].get("match") != "learned alias"  # not active before approval
    alias = next(proposal for proposal in db.list_proposals() if proposal["kind"] == "alias")
    feedback.approve(alias["id"])
    top = indicators.search("rural power")[0]
    assert top["id"] == "EG.ELC.ACCS.RU.ZS" and top["match"] == "learned alias"
    case = next(proposal for proposal in db.list_proposals() if proposal["kind"] == "eval_case")
    feedback.approve(case["id"])
    assert "rural power" in (data_dir / "evals" / "candidates.jsonl").read_text()
    with pytest.raises(ValueError):
        feedback.approve(case["id"])  # already decided


def test_alias_must_be_a_real_indicator():
    with pytest.raises(ValueError):
        feedback.submit("t1", -1, "q", "a", phrase="x", code="NOT.A.REAL.CODE")
    with pytest.raises(ValueError):
        feedback.submit("t1", -1, "q", "a", phrase="x", code="../etc/passwd")
