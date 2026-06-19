from __future__ import annotations

from app.services.event_narrative_polisher import EventNarrativePolisher
from app.services.llm_budget import LLMCallLedger, LLMBudgetProfile
from app.services.match_simulator import Event
from app.services.roster_loader import PlayerSnapshot, TeamRoster


class FakeTextLLM:
    def __init__(self, replies: list[str] | None = None):
        self.replies = list(replies or ["精炼后的事件描述"])
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        return self.replies.pop(0) if self.replies else "精炼后的事件描述"


class EmptyContentLLM:
    def __init__(self):
        self.calls = []

    def chat(self, **kwargs):
        self.calls.append(kwargs)
        raise ValueError(
            "LLM返回内容为空（finish_reason=length, reasoning_tokens=77, reasoning_content_length=180）"
        )


def _budget(*, narrative_polish_count: int, hard_cap_calls: int = 20) -> LLMBudgetProfile:
    return LLMBudgetProfile.from_dict(
        {
            "profile_key": "custom",
            "overrides": {
                "narrative_polish_count": narrative_polish_count,
                "hard_cap_calls": hard_cap_calls,
            },
        }
    )


def _player(index: int, *, team: str = "HOM", name: str | None = None) -> PlayerSnapshot:
    return PlayerSnapshot(
        id=f"{team}_{index}",
        name=name or f"{team}球员{index}",
        name_en=f"{team} Player {index}",
        position_primary="ST",
        position_class="FW",
        age=25,
        derived={},
        expected_role="starter",
        expected_minutes_share=0.9,
        availability={"status": "available"},
        shirt_number=index,
        club_fifa="Test FC",
    )


def _squads() -> tuple[TeamRoster, TeamRoster]:
    home = TeamRoster(iso3="HOM", team_fifa="Home", players=[_player(i, team="HOM") for i in range(1, 27)])
    away = TeamRoster(iso3="AWY", team_fifa="Away", players=[_player(i, team="AWY") for i in range(1, 27)])
    return home, away


def _goal() -> Event:
    scorer = _squads()[0].players[8]
    assist = _squads()[0].players[6]
    return Event(
        minute=34,
        type="GOAL",
        side="home",
        actor_player=scorer,
        assist_player=assist,
        score_after=(1, 0),
    )


def test_polish_template_fallback_when_budget_zero():
    llm = FakeTextLLM()
    budget = _budget(narrative_polish_count=0)
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    polisher = EventNarrativePolisher(budget=budget, ledger=ledger, squads=_squads(), llm_client=llm)

    rows = polisher.polish([_goal()], scenario_key="home_normal_away_normal")

    assert rows[0]["description"] == "home 34' HOM球员9 破门"
    assert rows[0]["narrative_source"] == "template"
    assert llm.calls == []
    assert ledger.summary()["total_calls"] == 0


def test_player_whitelist_blocks_llm_hallucination():
    llm = FakeTextLLM(["Maradona 禁区内破门"])
    budget = _budget(narrative_polish_count=3)
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    polisher = EventNarrativePolisher(budget=budget, ledger=ledger, squads=_squads(), llm_client=llm)

    rows = polisher.polish([_goal()], scenario_key="home_normal_away_normal")

    assert rows[0]["description"] == "home 34' HOM球员9 破门"
    assert rows[0]["narrative_source"] == "template"
    assert ledger.summary()["by_role"]["narrative_polisher"]["calls"] == 1
    assert ledger.summary()["failures"][0]["reason"] == "player_whitelist_failed"


def test_empty_reasoning_only_response_falls_back_to_template_with_clear_reason():
    llm = EmptyContentLLM()
    budget = _budget(narrative_polish_count=3)
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    polisher = EventNarrativePolisher(budget=budget, ledger=ledger, squads=_squads(), llm_client=llm)

    rows = polisher.polish([_goal()], scenario_key="home_normal_away_normal")

    assert rows[0]["description"] == "home 34' HOM球员9 破门"
    assert rows[0]["narrative_source"] == "template"
    failure = ledger.summary()["failures"][0]
    assert failure["reason"] == "empty_content"
    assert "reasoning_tokens=77" in failure["error"]


def test_polish_only_top_n_scenarios():
    llm = FakeTextLLM(["白名单内客观描述"])
    budget = _budget(narrative_polish_count=3)
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    polisher = EventNarrativePolisher(budget=budget, ledger=ledger, squads=_squads(), llm_client=llm)

    polished = polisher.polish([_goal()], scenario_key="home_normal_away_underperform")
    fallback = polisher.polish([_goal()], scenario_key="home_underperform_away_normal")

    assert polished[0]["description"] == "白名单内客观描述"
    assert polished[0]["narrative_source"] == "llm"
    assert fallback[0]["description"] == "home 34' HOM球员9 破门"
    assert fallback[0]["narrative_source"] == "template"
    assert len(llm.calls) == 1
