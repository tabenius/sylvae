"""Tier -> backend routing.

`--backend auto` was broken from the moment it shipped: resolve_backend
routed tier 'frontier' -- and unset tier, the default for every undeclared
skill -- to the Anthropic backend, for which no credentials exist or can be
obtained on this machine. It went unnoticed because manual testing always
passed an explicit --backend, and the single auto test used disk-report,
which is tier: cheap and takes the one working branch.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from sylvae.loader import Skill
from sylvae.runner import (
    DEFAULT_TIER_BACKENDS,
    BACKENDS,
    resolve_backend,
    tier_backends,
)


def _skill(tier: str | None) -> Skill:
    return Skill(slug="s", name="s", description="d", instructions="i", path=Path("."), tier=tier)


def test_every_default_tier_target_is_a_real_backend():
    """The bug in one assertion: the default map pointed at a backend that
    could not run. Any future edit that repeats that fails here."""
    for tier, backend in DEFAULT_TIER_BACKENDS.items():
        assert backend in BACKENDS, f"tier {tier!r} targets unknown backend {backend!r}"


def test_frontier_no_longer_routes_to_anthropic():
    assert DEFAULT_TIER_BACKENDS["frontier"] != "anthropic"


def test_cheap_tier_routes_to_a_local_model():
    assert resolve_backend(_skill("cheap"), "auto") == DEFAULT_TIER_BACKENDS["cheap"]


def test_frontier_tier_routes_to_the_frontier_target():
    assert resolve_backend(_skill("frontier"), "auto") == DEFAULT_TIER_BACKENDS["frontier"]


def test_unset_tier_uses_the_frontier_target_not_the_cheap_one():
    """An author who has not thought about the tradeoff should not get
    silently downgraded output."""
    assert resolve_backend(_skill(None), "auto") == DEFAULT_TIER_BACKENDS["frontier"]


def test_explicit_backend_is_never_overridden():
    assert resolve_backend(_skill("cheap"), "anthropic") == "anthropic"
    assert resolve_backend(_skill(None), "ollama") == "ollama"


def test_tier_targets_are_configurable_by_environment(monkeypatch):
    """Hardcoding the map is what produced the original bug; the right
    target genuinely differs per operator."""
    monkeypatch.setenv("SYLVAE_BACKEND_FRONTIER", "claudecode")

    assert tier_backends()["frontier"] == "claudecode"
    assert resolve_backend(_skill("frontier"), "auto") == "claudecode"


def test_unknown_backend_in_environment_override_is_refused(monkeypatch):
    monkeypatch.setenv("SYLVAE_BACKEND_CHEAP", "not-a-backend")

    with pytest.raises(ValueError):
        tier_backends()


# --------------------------------------------------------------------------
# Missing credentials are a configuration problem, not a quality problem.
# Recording them as 'failed' would make a permanently-unusable backend look
# to adaptive routing like a backend that runs and answers badly.
# --------------------------------------------------------------------------

@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_absent_credentials_report_unavailable_not_failed(mock_cls):
    from sylvae.backends.anthropic_backend import AnthropicBackend

    client = MagicMock()
    client.api_key = None
    client.auth_token = None
    mock_cls.return_value = client

    result = AnthropicBackend().run("prompt", _skill(None))

    assert result.status == "unavailable"
    assert "credential" in result.error.lower()
    client.messages.create.assert_not_called()


@patch("sylvae.backends.anthropic_backend.Anthropic")
def test_rejected_credentials_also_report_unavailable(mock_cls):
    import httpx
    from anthropic import AuthenticationError

    from sylvae.backends.anthropic_backend import AnthropicBackend

    client = MagicMock()
    client.api_key = "sk-present-but-wrong"
    client.messages.create.side_effect = AuthenticationError(
        message="invalid x-api-key",
        response=httpx.Response(401, request=httpx.Request("POST", "https://api.anthropic.com")),
        body=None,
    )
    mock_cls.return_value = client

    result = AnthropicBackend(api_key="wrong").run("prompt", _skill(None))

    assert result.status == "unavailable"
