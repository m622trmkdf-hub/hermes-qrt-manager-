from clan_manager_bot.hermes_client import (
    _clean_report_text,
    member_analytics_to_dict,
    merge_hermes_candidate_score,
    parse_hermes_candidate_json,
)
from clan_manager_bot.models import CandidateScore, MemberAnalytics
from clan_manager_bot.scoring import ScoringInputs


def test_parse_hermes_candidate_json_plain_and_fenced() -> None:
    plain = '{"score": 88, "verdict": "Рекомендован", "reasons": ["ok"], "risks": []}'
    assert parse_hermes_candidate_json(plain)["score"] == 88

    fenced = '```json\n{"score": 71, "verdict": "Условно рекомендован", "reasons": ["ok"], "risks": []}\n```'
    assert parse_hermes_candidate_json(fenced)["score"] == 71


def test_merge_hermes_candidate_score_clamps_and_keeps_identity() -> None:
    data = ScoringInputs(
        application_id=10,
        user_id=20,
        username="driver",
        experience_text="",
        activity_text="",
        about_text="",
        warnings_count=0,
    )
    fallback = CandidateScore(10, 20, "driver", 55, "C", "Не рекомендован", ["fallback"], ["risk"])
    merged = merge_hermes_candidate_score(
        data,
        fallback,
        {"score": 130, "verdict": "Рекомендован", "reasons": ["active"], "risks": ["none"]},
    )

    assert merged.application_id == 10
    assert merged.user_id == 20
    assert merged.score == 100
    assert merged.grade == "A"
    assert merged.verdict == "Рекомендован"
    assert merged.reasons[0].startswith("Hermes Agent:")


def test_member_analytics_to_dict_and_report_cleanup() -> None:
    item = MemberAnalytics(
        user_id=1,
        username="leader",
        messages_count=50,
        active_days=7,
        warnings_count=0,
        helpful_answers=10,
        toxicity_flags=0,
    )

    assert member_analytics_to_dict(item)["helpful_answers"] == 10
    assert _clean_report_text("```markdown\nОтчет\n```").startswith("Hermes Agent analytics\nОтчет")
