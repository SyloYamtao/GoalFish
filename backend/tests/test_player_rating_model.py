import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.clean_fm_wc2026 import compute_derived  # noqa: E402


def _base(**overrides):
    attrs = {
        "fm_ca": 150,
        "finishing": 10,
        "dribbling": 10,
        "first_touch": 10,
        "free_kick": 10,
        "heading": 10,
        "long_shots": 10,
        "marking": 10,
        "passing": 10,
        "penalties": 10,
        "tackling": 10,
        "technique": 10,
        "aggression": 10,
        "anticipation": 10,
        "bravery": 10,
        "composure": 10,
        "concentration": 10,
        "decisions": 10,
        "flair": 10,
        "off_the_ball": 10,
        "positioning_def": 10,
        "teamwork": 10,
        "vision": 10,
        "work_rate": 10,
        "acceleration": 10,
        "agility": 10,
        "balance": 10,
        "jumping": 10,
        "natural_fitness": 10,
        "pace": 10,
        "stamina": 10,
        "strength": 10,
        "gk_aerial_ability": 10,
        "gk_command_of_area": 10,
        "gk_communication": 10,
        "gk_handling": 10,
        "gk_kicking": 10,
        "gk_one_on_ones": 10,
        "gk_reflexes": 10,
        "gk_rushing_out": 10,
        "gk_throwing": 10,
    }
    attrs.update(overrides)
    return attrs


def test_overall_is_not_ca_divided_by_two():
    raw = _base(
        fm_ca=180,
        passing=20,
        technique=20,
        vision=20,
        decisions=19,
        first_touch=19,
        composure=19,
        off_the_ball=18,
        work_rate=18,
        stamina=18,
    )

    derived = compute_derived(raw, "CM")

    assert derived["overall"] != 90.0
    assert derived["overall"] > 70
    assert derived["score_source"] == "attribute_role_trait_bio_weight_v3"


def test_centre_back_rewards_aerial_duels_and_defensive_mentals():
    weak_duel_cb = _base(passing=18, technique=18, vision=18)
    elite_duel_cb = _base(
        heading=18,
        jumping=18,
        strength=18,
        bravery=18,
        tackling=17,
        marking=17,
        positioning_def=17,
        anticipation=17,
        concentration=17,
    )

    weak = compute_derived(weak_duel_cb, "CB")
    elite = compute_derived(elite_duel_cb, "CB")

    assert elite["overall"] - weak["overall"] >= 15
    assert elite["role_scores"]["aerial_duel"] >= 85
    assert weak["role_scores"]["aerial_duel"] <= 55


def test_midfielder_rewards_passing_technique_vision_and_decisions():
    runner = _base(pace=18, acceleration=18, strength=18, jumping=18)
    controller = _base(
        passing=18,
        technique=18,
        first_touch=18,
        vision=18,
        decisions=18,
        composure=17,
        teamwork=17,
        off_the_ball=16,
    )

    runner_score = compute_derived(runner, "CM")
    controller_score = compute_derived(controller, "CM")

    assert controller_score["overall"] - runner_score["overall"] >= 12
    assert controller_score["passing"] >= 85


def test_striker_rewards_finishing_movement_and_composure():
    sprinter = _base(pace=19, acceleration=19, strength=18)
    scorer = _base(
        finishing=19,
        composure=18,
        off_the_ball=18,
        anticipation=18,
        first_touch=17,
        technique=16,
        heading=16,
        jumping=15,
    )

    sprinter_score = compute_derived(sprinter, "ST")
    scorer_score = compute_derived(scorer, "ST")

    assert scorer_score["overall"] - sprinter_score["overall"] >= 10
    assert scorer_score["finishing"] >= 85


def test_goalkeeper_uses_goalkeeper_specific_attributes():
    outfield_skills = _base(
        passing=20,
        technique=20,
        finishing=20,
        tackling=20,
        gk_reflexes=8,
        gk_handling=8,
        gk_one_on_ones=8,
        gk_aerial_ability=8,
    )
    keeper_skills = _base(
        passing=8,
        technique=8,
        finishing=8,
        tackling=8,
        gk_reflexes=18,
        gk_handling=18,
        gk_one_on_ones=18,
        gk_aerial_ability=17,
        gk_command_of_area=17,
        gk_communication=16,
        gk_kicking=15,
        gk_rushing_out=15,
    )

    outfield = compute_derived(outfield_skills, "GK")
    keeper = compute_derived(keeper_skills, "GK")

    assert keeper["overall"] - outfield["overall"] >= 25
    assert keeper["gk"] >= 85
    assert outfield["gk"] <= 45


def test_striker_traits_boost_relevant_finishing_and_movement_only_slightly():
    base = _base(
        finishing=14,
        composure=14,
        off_the_ball=14,
        anticipation=14,
        first_touch=13,
    )
    with_traits = _base(
        **base,
        player_traits="禁区杀手（隐藏习惯）\n第一时间射门\n乐于反越位",
    )

    plain = compute_derived(base, "ST")
    boosted = compute_derived(with_traits, "ST")

    assert 1.5 <= boosted["overall"] - plain["overall"] <= 4.0
    assert boosted["finishing"] > plain["finishing"]
    assert boosted["role_scores"]["movement"] > plain["role_scores"]["movement"]
    assert boosted["role_scores"]["trait_adjustment"] > 0
    assert boosted["role_scores"]["trait_count"] == 3


def test_centre_back_traits_boost_defensive_and_build_up_duties():
    base = _base(
        tackling=14,
        marking=14,
        positioning_def=14,
        heading=14,
        passing=12,
        technique=12,
        vision=12,
    )
    irrelevant_shooting_trait = _base(**base, player_traits="第一时间射门\n角度刁钻的射门")
    role_traits = _base(**base, player_traits="倒地铲球\n长距离传球\n把球带出防守区域")

    irrelevant = compute_derived(irrelevant_shooting_trait, "CB")
    boosted = compute_derived(role_traits, "CB")

    assert boosted["overall"] > irrelevant["overall"]
    assert boosted["defense"] > irrelevant["defense"]
    assert boosted["passing"] > irrelevant["passing"]
    assert boosted["role_scores"]["trait_adjustment"] > irrelevant["role_scores"]["trait_adjustment"]


def test_risky_traits_apply_small_negative_adjustment():
    base = _base(
        passing=15,
        technique=15,
        vision=15,
        decisions=15,
        teamwork=15,
        concentration=15,
    )
    risky = _base(**base, player_traits="与裁判争论\n激怒对手")

    plain = compute_derived(base, "CM")
    adjusted = compute_derived(risky, "CM")

    assert adjusted["overall"] < plain["overall"]
    assert -2.0 <= adjusted["role_scores"]["trait_adjustment"] < 0


def test_height_context_rewards_centre_back_aerial_profile_modestly():
    compact_cb = _base(
        height_cm=178,
        age=27,
        heading=15,
        jumping=15,
        strength=15,
        bravery=15,
        tackling=15,
        marking=15,
        positioning_def=15,
    )
    tall_cb = {**compact_cb, "height_cm": 194}

    compact = compute_derived(compact_cb, "CB")
    tall = compute_derived(tall_cb, "CB")

    assert tall["role_scores"]["aerial_duel"] > compact["role_scores"]["aerial_duel"]
    assert tall["role_scores"]["power"] >= compact["role_scores"]["power"]
    assert tall["role_scores"]["height_adjustment"] > compact["role_scores"]["height_adjustment"]
    assert 0.5 <= tall["overall"] - compact["overall"] <= 3.0


def test_goalkeeper_height_context_affects_command_of_area():
    shorter = _base(
        height_cm=181,
        age=29,
        gk_reflexes=16,
        gk_handling=16,
        gk_one_on_ones=16,
        gk_aerial_ability=15,
        gk_command_of_area=15,
        gk_communication=15,
    )
    taller = {**shorter, "height_cm": 198}

    shorter_score = compute_derived(shorter, "GK")
    taller_score = compute_derived(taller, "GK")

    assert taller_score["gk"] > shorter_score["gk"]
    assert taller_score["role_scores"]["keeper_command"] > shorter_score["role_scores"]["keeper_command"]
    assert taller_score["role_scores"]["height_adjustment"] > shorter_score["role_scores"]["height_adjustment"]
    assert 0.5 <= taller_score["overall"] - shorter_score["overall"] <= 3.0


def test_age_context_penalizes_very_young_midfielder_maturity_modestly():
    prospect = _base(
        age=18,
        height_cm=181,
        passing=16,
        technique=16,
        first_touch=16,
        vision=16,
        decisions=16,
        concentration=16,
        composure=16,
        teamwork=16,
    )
    prime = {**prospect, "age": 26}

    prospect_score = compute_derived(prospect, "CM")
    prime_score = compute_derived(prime, "CM")

    assert prime_score["overall"] > prospect_score["overall"]
    assert prospect_score["role_scores"]["game_intelligence"] < prime_score["role_scores"]["game_intelligence"]
    assert prospect_score["role_scores"]["age_adjustment"] < 0
    assert 0.5 <= prime_score["overall"] - prospect_score["overall"] <= 3.0


def test_age_context_reduces_veteran_winger_physical_output():
    prime = _base(
        age=27,
        height_cm=178,
        pace=17,
        acceleration=17,
        agility=16,
        balance=16,
        stamina=16,
        dribbling=16,
        crossing=15,
        finishing=15,
        off_the_ball=15,
    )
    veteran = {**prime, "age": 36}

    prime_score = compute_derived(prime, "WG")
    veteran_score = compute_derived(veteran, "WG")

    assert veteran_score["overall"] < prime_score["overall"]
    assert veteran_score["pace"] < prime_score["pace"]
    assert veteran_score["role_scores"]["mobility"] < prime_score["role_scores"]["mobility"]
    assert veteran_score["role_scores"]["age_adjustment"] < 0
    assert 0.5 <= prime_score["overall"] - veteran_score["overall"] <= 4.0
