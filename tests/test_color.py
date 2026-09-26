import io

from sylvae.color import color_enabled, paint, status_styles


def test_color_disabled_for_non_tty_stream():
    assert color_enabled(io.StringIO()) is False


def test_no_color_env_forces_off_even_with_force_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color_enabled(io.StringIO()) is False


def test_force_color_enables_without_a_tty(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert color_enabled(io.StringIO()) is True


def test_term_dumb_disables(monkeypatch):
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    monkeypatch.setenv("TERM", "dumb")
    assert color_enabled(io.StringIO()) is False


def test_paint_wraps_only_when_enabled():
    assert paint("ok", "green", enabled=True) == "\033[32mok\033[0m"
    assert paint("ok", "green", enabled=False) == "ok"
    # No styles -> unchanged even when enabled.
    assert paint("ok", enabled=True) == "ok"


def test_status_styles_known_and_unknown():
    assert status_styles("passed") == ("green",)
    assert status_styles("failed") == ("red",)
    assert status_styles("mystery") == ()
