from clan_manager_bot.handlers import _as_int, _as_text


def test_safe_value_converters() -> None:
    assert _as_int("42") == 42
    assert _as_int(None) == 0
    assert _as_int("bad", default=7) == 7

    assert _as_text(None) == ""
    assert _as_text(123) == "123"
