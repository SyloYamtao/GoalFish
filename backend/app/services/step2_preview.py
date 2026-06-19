"""Step1-complete preview data for the Step2 setup screen."""

from __future__ import annotations

from typing import Any

from ..db.models import PredictionPlayerDatasetRecord, ProjectRecord, utc_now
from ..db.session import get_session
from .external_data.team_name_normalizer import TeamNameNormalizer
from .football_data_extractor import FootballDataExtractor
from .football_goal_model import ExternalDataPool
from .graph_evidence_query import GraphEvidenceQuery
from .prediction_config import (
    DEFAULT_PLAYER_DATASET_ID,
    _combined_text,
    _dataset_summary_contract,
    _external_offline_enabled,
    _external_sources_contract,
    _external_sources_etag,
    _identity_update_from_extracted,
    _load_graph_snapshot_for_config,
    _resolve_match_identity,
    _roster_contract,
    _roster_with_display_name,
)
from .roster_loader import RosterLoader, apply_graph_facts, apply_source_availability


STEP2_PREVIEW_METADATA_KEY = "step2_preview"


class Step2PreviewService:
    """Build and persist lightweight Step2 display data after Step1 finishes."""

    def build_preview(
        self,
        *,
        project_id: str,
        graph_id: str | None,
        player_dataset_id: str = DEFAULT_PLAYER_DATASET_ID,
        force: bool = False,
    ) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                raise KeyError(f"project not found: {project_id}")
            metadata = dict(project.project_metadata or {})
            existing = metadata.get(STEP2_PREVIEW_METADATA_KEY)
            if (
                not force
                and isinstance(existing, dict)
                and existing.get("graph_id") == graph_id
                and existing.get("player_dataset_id") == player_dataset_id
            ):
                return existing

        preview = self._assemble_preview(
            project_id=project_id,
            graph_id=graph_id,
            player_dataset_id=player_dataset_id,
        )
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                raise KeyError(f"project not found: {project_id}")
            metadata = dict(project.project_metadata or {})
            metadata[STEP2_PREVIEW_METADATA_KEY] = preview
            project.project_metadata = metadata
        return preview

    def get_preview(self, project_id: str) -> dict[str, Any] | None:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                raise KeyError(f"project not found: {project_id}")
            preview = (project.project_metadata or {}).get(STEP2_PREVIEW_METADATA_KEY)
            return preview if isinstance(preview, dict) else None

    def _assemble_preview(
        self,
        *,
        project_id: str,
        graph_id: str | None,
        player_dataset_id: str,
    ) -> dict[str, Any]:
        project_snapshot = self._project_snapshot(project_id)
        requirement = project_snapshot.get("simulation_requirement") or ""
        graph_snapshot = _load_graph_snapshot_for_config(graph_id, [])
        entities = graph_snapshot.get("entities") or []
        source_text = _combined_text(project_snapshot, entities, requirement)
        normalizer = TeamNameNormalizer()
        warnings: list[str] = []

        home_iso3, away_iso3, home, away = _resolve_match_identity(
            requirement=requirement,
            source_text=source_text,
            graph_entities=entities,
            graph_id=graph_id,
            home_team=None,
            away_team=None,
            normalizer=normalizer,
        )

        dataset_id = player_dataset_id or DEFAULT_PLAYER_DATASET_ID
        loader = RosterLoader()
        home_roster, away_roster = loader.snapshot(dataset_id, home_iso3, away_iso3)
        home_roster = _roster_with_display_name(home_roster, home)
        away_roster = _roster_with_display_name(away_roster, away)
        if not (home_roster.players and away_roster.players):
            warnings.append("roster_missing_or_empty")

        extracted: dict[str, Any] = {}
        try:
            extracted = FootballDataExtractor(normalizer=normalizer)._regex_fallback(source_text).to_dict()
        except Exception as exc:  # noqa: BLE001 - preview must not block graph completion.
            warnings.append(f"preview_extraction_failed: {type(exc).__name__}")

        identity_update = _identity_update_from_extracted(
            current_home_iso3=home_iso3,
            current_away_iso3=away_iso3,
            current_home=home,
            current_away=away,
            extracted=extracted,
            normalizer=normalizer,
            dataset_id=dataset_id,
        )
        if identity_update:
            home_iso3, away_iso3, home, away = identity_update
            home_roster, away_roster = loader.snapshot(dataset_id, home_iso3, away_iso3)
            home_roster = _roster_with_display_name(home_roster, home)
            away_roster = _roster_with_display_name(away_roster, away)
            warnings.append("match_identity_corrected_from_extracted_context")

        try:
            graph_facts = GraphEvidenceQuery().for_match(
                home_iso3=home_iso3,
                away_iso3=away_iso3,
                graph_id=graph_id or "",
                dataset_id=dataset_id,
            )
            apply_graph_facts(home_roster, graph_facts)
            apply_graph_facts(away_roster, graph_facts)
            warnings.extend(list(getattr(graph_facts, "warnings", []) or []))
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"preview_graph_facts_failed: {type(exc).__name__}")

        apply_source_availability(home_roster, source_text)
        apply_source_availability(away_roster, source_text)

        squads = loader.to_snapshot(home_roster, away_roster)
        dataset = self._dataset(dataset_id)
        external_sources = self._external_sources(home_iso3, away_iso3)

        return {
            "project_id": project_id,
            "graph_id": graph_id,
            "match_name": f"{home} vs {away}",
            "home_team": home,
            "away_team": away,
            "home_iso3": home_iso3,
            "away_iso3": away_iso3,
            "player_dataset_id": dataset_id,
            "dataset_summary": _dataset_summary_contract(
                dataset_id=dataset_id,
                source_label=dataset.source_label if dataset else None,
                scope_label=dataset.scope_label if dataset else None,
                squads=squads,
            ),
            "roster": _roster_contract(
                dataset_id=dataset_id,
                dataset=dataset,
                squads=squads,
            ),
            "external_sources": external_sources,
            "warnings": warnings,
            "status": "preview_ready",
            "source": "step1_graph_completed_preview",
            "created_at": utc_now().isoformat(),
        }

    def _project_snapshot(self, project_id: str) -> dict[str, Any]:
        with get_session() as session:
            project = session.get(ProjectRecord, project_id)
            if not project:
                return {}
            return {
                "project_id": project.project_id,
                "simulation_requirement": project.simulation_requirement or "",
                "files": project.files or [],
                "extracted_text": project.extracted_text or "",
                "analysis_summary": project.analysis_summary or "",
            }

    def _dataset(self, dataset_id: str) -> PredictionPlayerDatasetRecord | None:
        with get_session() as session:
            return session.get(PredictionPlayerDatasetRecord, dataset_id)

    def _external_sources(self, home_iso3: str, away_iso3: str) -> list[dict[str, Any]]:
        try:
            pool = ExternalDataPool().fetch_for_match(
                home_iso3,
                away_iso3,
                since_year=2014,
                sources=["intl_results", "national_elo", "fifa_ranking"],
                offline=_external_offline_enabled(),
            )
            payload = _external_sources_etag(pool)
            rows = _external_sources_contract(payload)
            if not any(row.get("key") == "fifa_ranking" for row in rows):
                rows.append({"key": "fifa_ranking", "status": "synced", "rows": None, "fetched_at": None, "etag": None})
            return rows
        except Exception as exc:  # noqa: BLE001
            return [
                {"key": "intl_results", "status": "error", "rows": None, "fetched_at": None, "etag": None, "error": str(exc)},
                {"key": "national_elo", "status": "skipped", "rows": None, "fetched_at": None, "etag": None},
                {"key": "fifa_ranking", "status": "skipped", "rows": None, "fetched_at": None, "etag": None},
            ]


def build_step2_preview_best_effort(project_id: str, graph_id: str | None, *, logger: Any | None = None) -> dict[str, Any] | None:
    try:
        return Step2PreviewService().build_preview(project_id=project_id, graph_id=graph_id, force=True)
    except Exception as exc:  # noqa: BLE001 - graph completion should not fail on preview issues.
        if logger:
            logger.warning("Step2 preview build failed: project_id=%s graph_id=%s error=%s", project_id, graph_id, exc)
        return None
