from __future__ import annotations

from types import SimpleNamespace

from app.services.coach_jury import SCENARIO_TEMPLATE
from app.services.coach_llm_panel import (
    ROLES,
    CoachLLMPanel,
    CoachPanelInputs,
    clip_verdict,
)
from app.services.graph_evidence_query import GraphFacts, PlayerAvailability
from app.services.llm_budget import LLMCallLedger, LLMBudgetProfile
from app.services.roster_loader import PlayerSnapshot, TeamRoster
from app.services.team_strength_estimator import TeamStrengthEstimator


class FakeLLM:
    def __init__(self, result: dict | None = None):
        self.result = result
        self.calls = []

    def chat_json(self, **kwargs):
        self.calls.append(kwargs)
        return self.result or _llm_verdict()


def _player(
    index: int,
    *,
    team_prefix: str = "H",
    position: str = "ST",
    attack: float = 80,
    defense: float = 60,
    status: str = "available",
) -> PlayerSnapshot:
    return PlayerSnapshot(
        id=f"{team_prefix}{index}",
        name=f"{team_prefix}球员{index}",
        name_en=f"{team_prefix} Player {index}",
        position_primary=position,
        position_class="GK" if position == "GK" else "FW" if position in {"ST", "WG"} else "MF",
        age=22 + index,
        derived={
            "overall": (attack + defense) / 2,
            "attack": attack,
            "defense": defense,
            "pace": attack - 5,
            "finishing": attack,
            "passing": 70,
            "set_piece": 65,
            "gk": 86 if position == "GK" else 0,
        },
        expected_role="starter",
        expected_minutes_share=1.0,
        availability={"status": status},
        shirt_number=index,
        club_fifa="Club",
    )


def _roster(iso3: str, prefix: str) -> TeamRoster:
    players = [_player(1, team_prefix=prefix, position="GK", attack=20, defense=70)]
    players.extend(
        _player(i, team_prefix=prefix, position="ST" if i % 2 else "WG", attack=96 - i)
        for i in range(2, 10)
    )
    return TeamRoster(iso3=iso3, team_fifa=f"Team {iso3}", players=players)


def _inputs(graph_facts=None) -> CoachPanelInputs:
    home = _roster("HOM", "H")
    away = _roster("AWY", "A")
    home_strength, away_strength = TeamStrengthEstimator().estimate_pair(
        home_roster=home,
        away_roster=away,
        fit_artifacts=SimpleNamespace(fit_status="uniform"),
        graph_facts=graph_facts,
    )
    extracted = SimpleNamespace(
        home_iso3="HOM",
        away_iso3="AWY",
        home_name_zh="主队",
        away_name_zh="客队",
        competition_meta={"tournament": "测试杯", "stage": "semi_final", "neutral_venue": True},
        key_narratives=[],
        injury_reports=[],
        tactical_notes=[],
    )
    return CoachPanelInputs.assemble(
        rosters=(home, away),
        team_strengths=(home_strength, away_strength),
        fit_artifacts=SimpleNamespace(
            fit_status="uniform",
            model_name="uniform_prior",
            diagnostics={"n_rows": 20, "aic": 123.4},
            attack_coef={"HOM": 0.1, "AWY": -0.1},
            defense_coef={"HOM": -0.1, "AWY": 0.1},
            home_advantage=0,
        ),
        extracted=extracted,
        graph_facts=graph_facts,
        scenario_template=list(SCENARIO_TEMPLATE),
    )


def _llm_verdict(**overrides) -> dict:
    votes = [
        {
            "scenario_key": scenario["scenario_key"],
            "vote": "support",
            "weight_delta_pct": 0,
            "rationale": "维持基准。",
            "evidence_refs": [{"type": "fit_summary"}],
        }
        for scenario in SCENARIO_TEMPLATE
    ]
    payload = {
        "role": "head_coach",
        "scenario_votes": votes,
        "team_xg_micro_adjustment": {"home": 0.0, "away": 0.0, "rationale": "无额外调整。"},
        "wld_pp_adjustment": None,
        "confidence_delta": 0.0,
        "summary": "维持九场景初始判断。",
    }
    payload.update(overrides)
    return payload


def _budget(*, roles: list[str], rounds: int = 1) -> LLMBudgetProfile:
    return LLMBudgetProfile.from_dict(
        {
            "profile_key": "custom",
            "overrides": {
                "coach_panel_roles": roles,
                "coach_deliberation_rounds": rounds,
                "hard_cap_calls": 10,
            },
        }
    )


def test_8_roles_defined():
    assert len(ROLES) == 8
    assert [role.key for role in ROLES] == [
        "head_coach",
        "attack",
        "defense",
        "transition",
        "set_piece",
        "goalkeeper",
        "fitness",
        "risk",
    ]


def test_clip_weight_delta_to_pm_30():
    raw = _llm_verdict(
        scenario_votes=[
            {
                "scenario_key": "x",
                "vote": "adjust",
                "weight_delta_pct": 50,
                "rationale": "越界。",
                "evidence_refs": [{"type": "fit_summary"}],
            }
        ]
    )

    clipped = clip_verdict(raw)

    assert clipped["scenario_votes"][0]["weight_delta_pct"] == 30
    assert clipped["clipped"] is True


def test_clip_xg_micro_adjustment():
    raw = _llm_verdict(
        team_xg_micro_adjustment={"home": 0.5, "away": -0.5, "rationale": "越界。"},
        wld_pp_adjustment={"home": 9, "draw": -9, "away": 0, "rationale": "越界。"},
        confidence_delta=0.4,
    )

    clipped = clip_verdict(raw)

    assert clipped["team_xg_micro_adjustment"]["home"] == 0.12
    assert clipped["team_xg_micro_adjustment"]["away"] == -0.12
    assert clipped["wld_pp_adjustment"]["home"] == 7
    assert clipped["wld_pp_adjustment"]["draw"] == -7
    assert clipped["confidence_delta"] == 0.15
    assert clipped["clipped"] is True


def test_fallback_to_hash_when_budget_zero():
    ledger = LLMCallLedger(config_id="cfg", budget=_budget(roles=[]))
    panel = CoachLLMPanel(budget=ledger.budget, ledger=ledger, llm_client=FakeLLM())

    verdicts = panel.deliberate(_inputs())

    assert len(verdicts) == 8
    assert ledger.summary()["total_calls"] == 0
    assert {verdict.metadata["source"] for verdict in verdicts} == {"coach_jury_fallback_v1"}


def test_role_specific_facts_in_prompt():
    panel = CoachLLMPanel(
        budget=_budget(roles=["attack"]),
        ledger=LLMCallLedger(config_id="cfg", budget=_budget(roles=["attack"])),
        llm_client=FakeLLM(),
    )

    prompt = panel.render_role_prompt("attack", _inputs())

    assert "前6名进攻球员" in prompt
    for name in ["H球员2", "H球员3", "H球员4", "H球员5", "H球员6", "H球员7"]:
        assert name in prompt
    for name in ["A球员2", "A球员3", "A球员4", "A球员5", "A球员6", "A球员7"]:
        assert name in prompt


def test_player_whitelist_in_risk_prompt():
    graph_facts = GraphFacts(
        player_availability={
            "H3": PlayerAvailability(status="injured", evidence_refs=[{"type": "graph_node", "id": "inj"}]),
        },
        player_team_iso3={"H3": "HOM", "A4": "AWY"},
        team_news={
            "AWY": [
                {
                    "player_id": "A4",
                    "player": "A球员4",
                    "type": "accumulated_yellow_cards",
                    "summary": "累黄停赛风险",
                    "evidence_refs": [{"type": "graph_node", "id": "yel"}],
                }
            ]
        },
    )
    panel = CoachLLMPanel(
        budget=_budget(roles=["risk"]),
        ledger=LLMCallLedger(config_id="cfg", budget=_budget(roles=["risk"])),
        llm_client=FakeLLM(),
    )

    prompt = panel.render_role_prompt("risk", _inputs(graph_facts))

    assert "伤停/停赛/累黄名单" in prompt
    assert "H球员3" in prompt
    assert "injured" in prompt
    assert "A球员4" in prompt
    assert "累黄停赛风险" in prompt


def test_evidence_refs_required():
    payload = _llm_verdict()
    payload["scenario_votes"][0].pop("evidence_refs")
    fake_llm = FakeLLM(payload)
    ledger = LLMCallLedger(config_id="cfg", budget=_budget(roles=["head_coach"]))
    panel = CoachLLMPanel(budget=ledger.budget, ledger=ledger, llm_client=fake_llm)

    verdict = panel.deliberate(_inputs())[0]

    assert verdict.scenario_votes[0]["evidence_refs"] == [
        {"type": "validation", "reason": "missing_evidence_refs"}
    ]


def test_deliberation_round_2_extra_call():
    fake_llm = FakeLLM(_llm_verdict())
    budget = _budget(roles=["head_coach"], rounds=2)
    ledger = LLMCallLedger(config_id="cfg", budget=budget)
    panel = CoachLLMPanel(budget=budget, ledger=ledger, llm_client=fake_llm)

    verdicts = panel.deliberate(_inputs())

    assert len(verdicts) == 1
    assert len(fake_llm.calls) == 2
    assert ledger.summary()["by_role"]["coach_head_coach"]["calls"] == 2
