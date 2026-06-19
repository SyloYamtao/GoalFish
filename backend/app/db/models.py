"""
Database models for persistent prediction task workflow state.
"""

import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from .session import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def new_uuid() -> str:
    return str(uuid.uuid4())


JsonDict = dict[str, Any]


class ProjectRecord(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True, default="created")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    files: Mapped[list[JsonDict]] = mapped_column(JSON, default=list)
    total_text_length: Mapped[int] = mapped_column(Integer, default=0)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    ontology: Mapped[Any | None] = mapped_column(JSON)
    analysis_summary: Mapped[str | None] = mapped_column(Text)
    graph_id: Mapped[str | None] = mapped_column(String(128), index=True)
    graph_build_task_id: Mapped[str | None] = mapped_column(String(64), index=True)
    simulation_requirement: Mapped[str | None] = mapped_column(Text)
    simulation_domain: Mapped[str] = mapped_column(String(64), default="football_match")
    chunk_size: Mapped[int] = mapped_column(Integer, default=500)
    chunk_overlap: Mapped[int] = mapped_column(Integer, default=50)
    error: Mapped[str | None] = mapped_column(Text)
    project_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)


class GraphMetadataRecord(Base):
    __tablename__ = "graph_metadata"

    graph_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str | None] = mapped_column(String(255))
    backend: Mapped[str] = mapped_column(String(32), index=True, default="graphiti")
    graph_metadata: Mapped[JsonDict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PredictionConfigRecord(Base):
    __tablename__ = "prediction_configs"

    prediction_config_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    graph_id: Mapped[str | None] = mapped_column(String(128), index=True)
    match_name: Mapped[str | None] = mapped_column(Text)
    home_team: Mapped[str | None] = mapped_column(Text)
    away_team: Mapped[str | None] = mapped_column(Text)
    competition: Mapped[str | None] = mapped_column(Text)
    kickoff_time: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, default="preparing")
    current_phase: Mapped[str | None] = mapped_column(String(64), index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    model_name: Mapped[str] = mapped_column(String(128), default="prior_poisson")
    model_version: Mapped[str] = mapped_column(String(64), default="v1")
    fit_status: Mapped[str] = mapped_column(String(32), index=True, default="fallback_prior")
    data_sufficiency: Mapped[str] = mapped_column(String(32), index=True, default="partial")
    source_document_ids: Mapped[Any | None] = mapped_column(JSON)
    graph_snapshot: Mapped[Any | None] = mapped_column(JSON)
    model_input_snapshot: Mapped[Any | None] = mapped_column(JSON)
    scenario_design_summary: Mapped[Any | None] = mapped_column(JSON)
    resume_policy_summary: Mapped[Any | None] = mapped_column(JSON)
    coach_jury_summary: Mapped[Any | None] = mapped_column(JSON)
    player_dataset_id: Mapped[str | None] = mapped_column(String(64), index=True)
    llm_budget_profile: Mapped[Any | None] = mapped_column(JSON)
    progress_messages: Mapped[list[JsonDict]] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)


class PredictionCoachAgentRecord(Base):
    __tablename__ = "prediction_coach_agents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_config_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="CASCADE"),
        index=True,
    )
    agent_index: Mapped[int] = mapped_column(Integer, index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    name: Mapped[str] = mapped_column(Text)
    expertise: Mapped[Any | None] = mapped_column(JSON)
    tactical_preference: Mapped[str | None] = mapped_column(Text)
    risk_tolerance: Mapped[str | None] = mapped_column(String(32))
    evidence_policy: Mapped[str | None] = mapped_column(Text)
    system_prompt: Mapped[str | None] = mapped_column(Text)
    agent_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_prediction_coach_agents_config_index", "prediction_config_id", "agent_index", unique=True),
    )


class PredictionCoachDiscussionRecord(Base):
    __tablename__ = "prediction_coach_discussions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_config_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="CASCADE"),
        index=True,
    )
    discussion_type: Mapped[str] = mapped_column(String(64), index=True)
    round_index: Mapped[int] = mapped_column(Integer, default=1)
    topic: Mapped[str] = mapped_column(Text)
    prompt: Mapped[str] = mapped_column(Text)
    summary: Mapped[str] = mapped_column(Text)
    consensus_score: Mapped[int] = mapped_column(Integer, default=70)
    disagreement_score: Mapped[int] = mapped_column(Integer, default=30)
    discussion_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PredictionCoachVoteRecord(Base):
    __tablename__ = "prediction_coach_votes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_config_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="CASCADE"),
        index=True,
    )
    prediction_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
    )
    discussion_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prediction_coach_discussions.id", ondelete="CASCADE"),
        index=True,
    )
    agent_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prediction_coach_agents.id", ondelete="CASCADE"),
        index=True,
    )
    target_type: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str | None] = mapped_column(String(64), index=True)
    vote: Mapped[str] = mapped_column(String(32), index=True)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    reasoning: Mapped[str | None] = mapped_column(Text)
    adjustment: Mapped[Any | None] = mapped_column(JSON)
    evidence_refs: Mapped[Any | None] = mapped_column(JSON)
    vote_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PredictionConfigScenarioCaseRecord(Base):
    __tablename__ = "prediction_config_scenario_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_config_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="CASCADE"),
        index=True,
    )
    home_state: Mapped[str] = mapped_column(String(32), index=True)
    away_state: Mapped[str] = mapped_column(String(32), index=True)
    scenario_key: Mapped[str] = mapped_column(String(96), index=True)
    scenario_name: Mapped[str] = mapped_column(Text)
    scenario_space: Mapped[str] = mapped_column(String(64), index=True)
    initial_weight: Mapped[int] = mapped_column(Integer)
    final_weight: Mapped[int] = mapped_column(Integer)
    key_drivers: Mapped[Any | None] = mapped_column(JSON)
    risk_factors: Mapped[Any | None] = mapped_column(JSON)
    coach_vote_summary: Mapped[Any | None] = mapped_column(JSON)
    model_constraints: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_prediction_config_scenario_cases_config_key", "prediction_config_id", "scenario_key", unique=True),
    )


class PredictionConfigResumeNodeRecord(Base):
    __tablename__ = "prediction_config_resume_nodes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_config_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="CASCADE"),
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer, index=True)
    label: Mapped[str] = mapped_column(Text)
    must_persist: Mapped[bool] = mapped_column(default=True)
    can_recompute: Mapped[bool] = mapped_column(default=False)
    resume_strategy: Mapped[str] = mapped_column(String(32), index=True)
    input_artifact_types: Mapped[Any | None] = mapped_column(JSON)
    output_artifact_types: Mapped[Any | None] = mapped_column(JSON)
    ui_replay_summary: Mapped[str | None] = mapped_column(Text)
    coach_vote_summary: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_prediction_config_resume_nodes_config_event", "prediction_config_id", "event_type", unique=True),
    )


class PredictionRunRecord(Base):
    __tablename__ = "prediction_runs"

    prediction_run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    prediction_config_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="SET NULL"),
        index=True,
    )
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    graph_id: Mapped[str | None] = mapped_column(String(128), index=True)
    match_name: Mapped[str | None] = mapped_column(Text)
    home_team: Mapped[str | None] = mapped_column(Text)
    away_team: Mapped[str | None] = mapped_column(Text)
    competition: Mapped[str | None] = mapped_column(Text)
    kickoff_time: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, default="created")
    current_phase: Mapped[str | None] = mapped_column(String(64), index=True)
    progress_percent: Mapped[int] = mapped_column(Integer, default=0)
    simulation_seed: Mapped[int | None] = mapped_column(Integer, index=True)
    n_sims: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)


class PredictionSourceDocumentRecord(Base):
    __tablename__ = "prediction_source_documents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str] = mapped_column(String(64), index=True)
    prediction_config_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="SET NULL"),
        index=True,
    )
    prediction_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
    )
    filename: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(128))
    checksum: Mapped[str | None] = mapped_column(String(128), index=True)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    parse_status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    parse_error: Mapped[str | None] = mapped_column(Text)
    document_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PredictionTeamStrengthRecord(Base):
    __tablename__ = "prediction_team_strengths"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_config_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prediction_configs.prediction_config_id", ondelete="CASCADE"),
        index=True,
    )
    prediction_run_id: Mapped[str | None] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )
    team_role: Mapped[str] = mapped_column(String(16), index=True)
    team_name: Mapped[str] = mapped_column(Text)
    attack_rating: Mapped[int] = mapped_column(Integer)
    defense_rating: Mapped[int] = mapped_column(Integer)
    possession_rating: Mapped[int] = mapped_column(Integer)
    transition_rating: Mapped[int] = mapped_column(Integer)
    set_piece_rating: Mapped[int] = mapped_column(Integer)
    discipline_rating: Mapped[int] = mapped_column(Integer)
    fitness_rating: Mapped[int] = mapped_column(Integer)
    goalkeeper_rating: Mapped[int] = mapped_column(Integer)
    home_away_adjustment: Mapped[int] = mapped_column(Integer, default=0)
    injury_adjustment: Mapped[int] = mapped_column(Integer, default=0)
    form_adjustment: Mapped[int] = mapped_column(Integer, default=0)
    evidence: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    strength_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_prediction_team_strengths_run_role", "prediction_run_id", "team_role", unique=True),
        Index("ix_prediction_team_strengths_config_role", "prediction_config_id", "team_role"),
    )


class PredictionScenarioCaseRecord(Base):
    __tablename__ = "prediction_scenario_cases"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    config_scenario_case_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prediction_config_scenario_cases.id", ondelete="SET NULL"),
        index=True,
    )
    prediction_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
    )
    home_state: Mapped[str] = mapped_column(String(32), index=True)
    away_state: Mapped[str] = mapped_column(String(32), index=True)
    scenario_space: Mapped[str] = mapped_column(String(64), index=True)
    scenario_module: Mapped[str] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer)
    strength_adjustments: Mapped[Any | None] = mapped_column(JSON)
    expected_goals: Mapped[Any | None] = mapped_column(JSON)
    win_draw_loss_probability: Mapped[Any | None] = mapped_column(JSON)
    scoreline_distribution: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    evidence: Mapped[Any | None] = mapped_column(JSON)
    case_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_prediction_scenario_cases_run_states", "prediction_run_id", "home_state", "away_state", unique=True),
    )


class PredictionScenarioSpaceRecord(Base):
    __tablename__ = "prediction_scenario_spaces"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
    )
    space_key: Mapped[str] = mapped_column(String(64), index=True)
    space_name: Mapped[str] = mapped_column(Text)
    weight: Mapped[int] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    scoreline_bias: Mapped[Any | None] = mapped_column(JSON)
    key_drivers: Mapped[Any | None] = mapped_column(JSON)
    risk_factors: Mapped[Any | None] = mapped_column(JSON)
    linked_scenario_case_ids: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    space_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_prediction_scenario_spaces_run_key", "prediction_run_id", "space_key", unique=True),
    )


class PredictionScorelineRecord(Base):
    __tablename__ = "prediction_scorelines"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
    )
    scenario_case_id: Mapped[str | None] = mapped_column(String(36), index=True)
    scenario_space: Mapped[str | None] = mapped_column(String(64), index=True)
    home_xg: Mapped[int] = mapped_column(Integer)
    away_xg: Mapped[int] = mapped_column(Integer)
    home_win_probability: Mapped[int] = mapped_column(Integer)
    draw_probability: Mapped[int] = mapped_column(Integer)
    away_win_probability: Mapped[int] = mapped_column(Integer)
    scoreline_distribution: Mapped[Any | None] = mapped_column(JSON)
    most_likely_score: Mapped[str | None] = mapped_column(String(32))
    total_goals_distribution: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    model_name: Mapped[str] = mapped_column(String(128), default="goalfish-heuristic-scoreline")
    model_version: Mapped[str] = mapped_column(String(64), default="v1")
    scoreline_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PredictionMatchEventRecord(Base):
    __tablename__ = "prediction_match_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
    )
    scenario_case_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prediction_scenario_cases.id", ondelete="CASCADE"),
        index=True,
    )
    round_num: Mapped[int | None] = mapped_column(Integer, index=True)
    minute: Mapped[int] = mapped_column(Integer, index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    scenario_space: Mapped[str | None] = mapped_column(String(64), index=True)
    scenario_module: Mapped[str | None] = mapped_column(Text)
    team: Mapped[str | None] = mapped_column(Text)
    player: Mapped[str | None] = mapped_column(Text)
    actor_player_id: Mapped[str | None] = mapped_column(String(64), index=True)
    assist_player_id: Mapped[str | None] = mapped_column(String(64), index=True)
    sim_seed: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str] = mapped_column(Text)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    score: Mapped[str | None] = mapped_column(String(32))
    evidence: Mapped[Any | None] = mapped_column(JSON)
    event_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_prediction_match_events_run_minute", "prediction_run_id", "minute"),
    )


class PredictionAnalystNoteRecord(Base):
    __tablename__ = "prediction_analyst_notes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
    )
    scenario_case_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("prediction_scenario_cases.id", ondelete="SET NULL"),
        index=True,
    )
    agent_role: Mapped[str] = mapped_column(String(64), index=True)
    scenario_space: Mapped[str | None] = mapped_column(String(64), index=True)
    related_event_id: Mapped[str | None] = mapped_column(String(36), index=True)
    claim: Mapped[str] = mapped_column(Text)
    reasoning: Mapped[str] = mapped_column(Text)
    evidence: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    note_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PredictionResultRecord(Base):
    __tablename__ = "prediction_results"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    prediction_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_runs.prediction_run_id", ondelete="CASCADE"),
        index=True,
        unique=True,
    )
    baseline_prediction: Mapped[Any | None] = mapped_column(JSON)
    scenario_cases_summary: Mapped[Any | None] = mapped_column(JSON)
    scenario_spaces_summary: Mapped[Any | None] = mapped_column(JSON)
    scoreline_summary: Mapped[Any | None] = mapped_column(JSON)
    match_events_summary: Mapped[Any | None] = mapped_column(JSON)
    analyst_notes_summary: Mapped[Any | None] = mapped_column(JSON)
    final_score_hypothesis: Mapped[Any | None] = mapped_column(JSON)
    uncertainty_factors: Mapped[Any | None] = mapped_column(JSON)
    confidence: Mapped[int] = mapped_column(Integer, default=60)
    result_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class PredictionPlayerDatasetRecord(Base):
    __tablename__ = "prediction_player_dataset"

    dataset_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    source_label: Mapped[str] = mapped_column(String(128))
    scope_label: Mapped[str] = mapped_column(String(128), index=True)
    ratings_schema: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    teams_count: Mapped[int] = mapped_column(Integer, default=0)
    players_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    dataset_metadata: Mapped[JsonDict] = mapped_column("metadata", JSON, default=dict)


class PredictionPlayerRecord(Base):
    __tablename__ = "prediction_player"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_player_dataset.dataset_id", ondelete="CASCADE"),
        index=True,
    )
    team_name: Mapped[str] = mapped_column(String(128), index=True)
    team_iso3: Mapped[str] = mapped_column(String(3), index=True)
    player_external_id: Mapped[str | None] = mapped_column(String(128), index=True)
    full_name: Mapped[str] = mapped_column(String(255))
    full_name_en: Mapped[str | None] = mapped_column(String(255))
    full_name_alt: Mapped[list[str]] = mapped_column(JSON, default=list)
    position_primary: Mapped[str] = mapped_column(String(8))
    position_secondary: Mapped[list[str]] = mapped_column(JSON, default=list)
    age: Mapped[int | None] = mapped_column(Integer)
    foot: Mapped[str | None] = mapped_column(String(8))
    height_cm: Mapped[int | None] = mapped_column(Integer)
    ratings: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    derived: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    availability: Mapped[JsonDict] = mapped_column(JSON, default=lambda: {"status": "available"})
    expected_role: Mapped[str] = mapped_column(String(16), default="rotation")
    expected_minutes_share: Mapped[float] = mapped_column(Numeric(4, 3), default=0.55)
    shirt_number: Mapped[int | None] = mapped_column(Integer)
    position_class: Mapped[str | None] = mapped_column(String(4))
    caps_intl: Mapped[int | None] = mapped_column(Integer)
    goals_intl: Mapped[int | None] = mapped_column(Integer)
    club_fifa: Mapped[str | None] = mapped_column(String(128))
    player_metadata: Mapped[JsonDict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("idx_player_dataset_team", "dataset_id", "team_name"),
        Index("idx_player_dataset_iso3", "dataset_id", "team_iso3"),
        Index("unique_shirt_number_per_team", "dataset_id", "team_iso3", "shirt_number", unique=True),
    )


class PredictionTeamMetadataRecord(Base):
    __tablename__ = "prediction_team_metadata"

    id: Mapped[str] = mapped_column(String(64), primary_key=True, default=new_uuid)
    dataset_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("prediction_player_dataset.dataset_id", ondelete="CASCADE"),
        index=True,
    )
    team_fifa: Mapped[str] = mapped_column(String(64))
    team_iso3: Mapped[str] = mapped_column(String(3), index=True)
    team_zh: Mapped[str | None] = mapped_column(String(64))
    group_label: Mapped[str | None] = mapped_column(String(8), index=True)
    head_coach: Mapped[str | None] = mapped_column(String(128))
    formation_primary: Mapped[str | None] = mapped_column(String(16))
    formation_secondary: Mapped[list[str]] = mapped_column(JSON, default=list)
    tactical_style: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    key_player_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    squad_status: Mapped[str] = mapped_column(String(16), default="final_26")
    team_metadata: Mapped[JsonDict] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        Index("idx_team_meta_dataset_fifa", "dataset_id", "team_fifa", unique=True),
        Index("idx_team_meta_iso3", "dataset_id", "team_iso3"),
        Index("idx_team_meta_group", "dataset_id", "group_label"),
    )


class PredictionTaskRecord(Base):
    __tablename__ = "prediction_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(32), index=True, default="created")
    active_attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    task_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    attempts: Mapped[list["TaskAttemptRecord"]] = relationship(
        back_populates="task",
        cascade="all, delete-orphan",
        primaryjoin="PredictionTaskRecord.id == TaskAttemptRecord.task_id",
    )


class TaskAttemptRecord(Base):
    __tablename__ = "task_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("prediction_tasks.id"), index=True)
    attempt_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True, default="created")
    source_attempt_id: Mapped[str | None] = mapped_column(String(36), index=True)
    rerun_from_event_type: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    config: Mapped[JsonDict] = mapped_column(JSON, default=dict)
    attempt_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    task: Mapped[PredictionTaskRecord] = relationship(back_populates="attempts")
    events: Mapped[list["TaskEventRecord"]] = relationship(back_populates="attempt", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_task_attempts_task_attempt_no", "task_id", "attempt_no", unique=True),
    )


class TaskEventRecord(Base):
    __tablename__ = "task_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("prediction_tasks.id"), index=True)
    attempt_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_attempts.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(64), index=True)
    sequence: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    input_artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_artifact_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    reused_from_event_id: Mapped[str | None] = mapped_column(String(36), index=True)
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    error_traceback: Mapped[str | None] = mapped_column(Text)
    event_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    attempt: Mapped[TaskAttemptRecord] = relationship(back_populates="events")

    __table_args__ = (
        Index("ix_task_events_attempt_event_type", "attempt_id", "event_type", unique=True),
        Index("ix_task_events_task_attempt_sequence", "task_id", "attempt_id", "sequence"),
    )


class TaskArtifactRecord(Base):
    __tablename__ = "task_artifacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("prediction_tasks.id"), index=True)
    attempt_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_attempts.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("task_events.id"), index=True)
    artifact_type: Mapped[str] = mapped_column(String(64), index=True)
    storage_kind: Mapped[str] = mapped_column(String(32), default="postgres_json")
    name: Mapped[str | None] = mapped_column(String(255))
    mime_type: Mapped[str | None] = mapped_column(String(128))
    content_text: Mapped[str | None] = mapped_column(Text)
    content_json: Mapped[Any | None] = mapped_column(JSON)
    file_path: Mapped[str | None] = mapped_column(Text)
    checksum: Mapped[str | None] = mapped_column(String(128))
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    artifact_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)


class PredictionReportRecord(Base):
    __tablename__ = "prediction_reports"

    report_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    simulation_id: Mapped[str] = mapped_column(String(64), index=True)
    graph_id: Mapped[str | None] = mapped_column(String(128), index=True)
    simulation_requirement: Mapped[str] = mapped_column(Text, default="")
    simulation_domain: Mapped[str] = mapped_column(String(64), default="football_match")
    status: Mapped[str] = mapped_column(String(32), index=True, default="pending")
    title: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    markdown_content: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(Text)
    report_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    sections: Mapped[list["PredictionReportSectionRecord"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        primaryjoin="PredictionReportRecord.report_id == PredictionReportSectionRecord.report_id",
    )


class PredictionReportSectionRecord(Base):
    __tablename__ = "prediction_report_sections"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    report_id: Mapped[str] = mapped_column(String(64), ForeignKey("prediction_reports.report_id"), index=True)
    section_index: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    section_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    report: Mapped[PredictionReportRecord] = relationship(back_populates="sections")

    __table_args__ = (
        Index("ix_prediction_report_sections_report_section", "report_id", "section_index", unique=True),
    )


class ReportConversationRecord(Base):
    __tablename__ = "report_conversations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    report_id: Mapped[str] = mapped_column(String(64), ForeignKey("prediction_reports.report_id"), index=True)
    simulation_id: Mapped[str] = mapped_column(String(64), index=True)
    target_type: Mapped[str] = mapped_column(String(32), index=True, default="report_agent")
    target_agent_id: Mapped[str | None] = mapped_column(String(128), index=True)
    title: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    conversation_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    messages: Mapped[list["ReportConversationMessageRecord"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        primaryjoin="ReportConversationRecord.id == ReportConversationMessageRecord.conversation_id",
    )

    __table_args__ = (
        Index(
            "ix_report_conversations_report_target",
            "report_id",
            "target_type",
            "target_agent_id",
        ),
    )


class ReportConversationMessageRecord(Base):
    __tablename__ = "report_conversation_messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    conversation_id: Mapped[str] = mapped_column(String(36), ForeignKey("report_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(32), index=True)
    content: Mapped[str] = mapped_column(Text)
    tool_calls: Mapped[Any | None] = mapped_column(JSON)
    sources: Mapped[Any | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    message_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    conversation: Mapped[ReportConversationRecord] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_report_conversation_messages_conversation_created", "conversation_id", "created_at"),
    )


class GraphBindingRecord(Base):
    __tablename__ = "graph_bindings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str] = mapped_column(String(36), ForeignKey("prediction_tasks.id"), index=True)
    attempt_id: Mapped[str] = mapped_column(String(36), ForeignKey("task_attempts.id"), index=True)
    project_id: Mapped[str | None] = mapped_column(String(64), index=True)
    graph_backend: Mapped[str] = mapped_column(String(32), index=True)
    graph_id: Mapped[str] = mapped_column(String(128), index=True)
    group_id: Mapped[str] = mapped_column(String(128), index=True)
    neo4j_uri: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True, default="creating")
    node_count: Mapped[int] = mapped_column(Integer, default=0)
    edge_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)
    binding_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)

    __table_args__ = (
        Index("ix_graph_bindings_attempt_graph", "attempt_id", "graph_id", unique=True),
    )


class LLMInteractionRecord(Base):
    __tablename__ = "llm_interactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("prediction_tasks.id"), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("task_attempts.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("task_events.id"), index=True)
    request_id: Mapped[str] = mapped_column(String(64), index=True)
    provider: Mapped[str | None] = mapped_column(String(64))
    base_url: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(255), index=True)
    operation: Mapped[str | None] = mapped_column(String(128), index=True)
    messages: Mapped[Any | None] = mapped_column(JSON)
    request_params: Mapped[Any | None] = mapped_column(JSON)
    response: Mapped[Any | None] = mapped_column(JSON)
    response_text: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), index=True)
    error_message: Mapped[str | None] = mapped_column(Text)
    error_traceback: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int | None] = mapped_column(Integer)
    completion_tokens: Mapped[int | None] = mapped_column(Integer)
    total_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    interaction_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)


class CeleryJobRecord(Base):
    __tablename__ = "celery_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_uuid)
    task_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("prediction_tasks.id"), index=True)
    attempt_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("task_attempts.id"), index=True)
    event_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("task_events.id"), index=True)
    celery_task_id: Mapped[str] = mapped_column(String(128), index=True)
    queue_name: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    job_metadata: Mapped[JsonDict] = mapped_column(JSON, default=dict)
