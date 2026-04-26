from clan_manager_bot.scoring import CandidateScorer, ScoringInputs


def test_candidate_scoring_range_and_grade() -> None:
    scorer = CandidateScorer()
    result = scorer.score(
        ScoringInputs(
            application_id=1,
            user_id=100,
            username="player1",
            experience_text="Играю 3 года, участвую в турнирах",
            activity_text="онлайн ежедневно 4 часа",
            about_text="Ответственный, помогаю новичкам и соблюдаю дисциплину",
            warnings_count=0,
        )
    )
    assert 0 <= result.score <= 100
    assert result.grade in {"A", "B", "C"}


def test_candidate_scoring_penalizes_toxicity() -> None:
    scorer = CandidateScorer()
    toxic = scorer.score(
        ScoringInputs(
            application_id=2,
            user_id=101,
            username="toxic",
            experience_text="fuck all",
            activity_text="1 час",
            about_text="вы все идиот",
            warnings_count=2,
        )
    )
    assert toxic.score < 70
    assert any("токс" in risk.lower() for risk in toxic.risks)
