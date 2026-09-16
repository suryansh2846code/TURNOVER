"""The Health agent, and the line it does not cross.

It was asked to "review honestly rather than encouragingly" with nothing to
review and no way to do arithmetic: no measurements, no `run_python`, and one
sentence of clinical boundary. It could hold a good conversation about training
and remember what you told it. It could not check anything.

Two halves are pinned here. That it now measures — and that the safety boundary
is attached to the *capability*, so a user who assembles their own nutrition
agent out of the same tools gets the same line.
"""
from __future__ import annotations

import pytest

from lodestone import metrics
from lodestone.agents import health_tools, prompt
from lodestone.agents.library import BY_ID
from lodestone.agents.presets import get_agent
from lodestone.agents.tools import TOOL_DEFS, TOOL_IMPLS


@pytest.fixture(autouse=True)
def clean():
    yield
    for name in metrics.known():
        metrics.forget(name)


def _prompt_for(agent_id: str) -> str:
    agent = get_agent(agent_id)
    return prompt.build(name=agent.name, role=agent.role,
                        system_prompt=agent.system_prompt,
                        actions=agent.actions, tools=agent.tools,
                        agent_id=agent.id)


# ── it can measure ───────────────────────────────────────────────────────
def test_it_holds_the_tools_that_make_measuring_possible():
    health = BY_ID["health"]
    for tool in ("whats_tracked", "measurement_history", "log_measurement",
                 "forget_measurement"):
        assert tool in health.tools, tool
        assert tool in TOOL_DEFS and tool in TOOL_IMPLS, tool


def test_it_can_do_arithmetic():
    """An agent that plans portions and reviews volume and cannot count."""
    assert "run_python" in BY_ID["health"].tools


def test_it_can_read_a_file():
    """Gym apps and food trackers export CSV, and that is where the rest is."""
    assert "read_file" in BY_ID["health"].tools


def test_it_works_with_nothing_connected():
    """First launch, no accounts. The user says a number; it records it."""
    assert BY_ID["health"].needs == []


def test_apple_health_is_where_it_expects_the_data():
    assert "apple_health" in BY_ID["health"].works_with
    assert "apple_health" in BY_ID["health"].recall_sources


# ── what the tools actually say ──────────────────────────────────────────
def test_with_no_data_it_is_told_to_say_so_not_to_estimate():
    out = health_tools.whats_tracked()
    assert "No measurements recorded yet" in out
    assert "Export All Health Data" in out, "it does not say how to get data in"


def test_it_is_told_which_metrics_have_nothing():
    """Otherwise it claims a trend for something it has never seen."""
    metrics.log_value("weight", 80, "kg")
    out = health_tools.whats_tracked()
    assert "weight" in out
    assert "No data for" in out and "sleep" in out
    assert "Do not guess" in out


def test_history_hands_back_the_arithmetic_not_a_list_of_numbers():
    from datetime import UTC, datetime, timedelta

    base = (datetime.now(UTC) - timedelta(days=60)).replace(
        hour=0, minute=0, second=0, microsecond=0)
    metrics.log_many(
        [{"metric": "weight", "value": 70 + i * 0.05 + (1.2 if i % 2 else -1.1),
          "unit": "kg", "at": (base + timedelta(days=i)).isoformat()}
         for i in range(60)], source="test")

    out = health_tools.measurement_history("weight", days=90)
    assert out.ok
    assert "SMOOTHED TREND" in out
    assert "per week" in out
    assert "use this, not the raw change" in out


def test_an_empty_metric_tells_it_not_to_invent_one():
    out = health_tools.measurement_history("sleep", days=30)
    assert "No sleep readings" in out
    assert "do not estimate" in out


def test_logging_reports_the_unit_it_was_converted_into():
    out = health_tools.log_measurement("weight", 170, "lb")
    assert out.ok
    assert "kg" in out, "it did not say what it actually stored"


def test_an_unknown_metric_lists_what_it_can_track():
    out = health_tools.log_measurement("aura", 5)
    assert not out.ok
    assert "weight" in out and "sleep" in out


def test_a_device_reading_is_not_deleted_by_the_agent():
    """Those are corrected by re-importing, not by the agent deciding to."""
    metrics.log_many([{"metric": "weight", "value": 79, "unit": "kg",
                       "at": "2026-09-02T00:00:00+00:00"}], source="apple_health")
    out = health_tools.forget_measurement("weight")
    assert not out.ok
    assert "re-import" in out
    assert len(metrics.history("weight", days=3650)) == 1


# ── the boundary ─────────────────────────────────────────────────────────
def test_the_safety_block_is_in_the_prompt():
    text = _prompt_for("health")
    assert "not a clinician" in text
    assert "never name a dose" in text
    assert "chest pain" in text


def test_it_is_told_never_to_present_a_remembered_number_as_a_measurement():
    """The exact failure this whole change exists to remove."""
    text = _prompt_for("health")
    assert "NEVER present a number you remembered as a measurement" in text


def test_the_boundary_follows_the_capability_not_the_template():
    """A user who builds their own nutrition agent gets the same line.

    It is the agent most likely to be asked something it should not answer, and
    it inherits no prose from the shipped Health template.
    """
    assert prompt._health_safety(["search_brain", "log_measurement"])
    assert not prompt._health_safety(["search_brain", "web_search"])


def test_restriction_is_named_once_and_not_lectured():
    """A disclaimer repeated every turn is one the user learns to skip."""
    block = prompt._HEALTH_SAFETY
    assert "ONCE" in block
    assert "do not lecture" in block.lower() or "without lecturing" in block
    assert "do not refuse ordinary" in block.lower()


def test_it_is_told_where_the_science_is_unsettled():
    assert "unsettled" in prompt._HEALTH_SAFETY


def test_the_generalist_gets_the_boundary_too():
    """Chief of Staff holds every tool, so it can be asked this too."""
    assert "not a clinician" in _prompt_for("chief-of-staff")
