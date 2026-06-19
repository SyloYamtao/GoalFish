"""业务服务模块。"""

from __future__ import annotations

__all__ = [
    "OntologyGenerator",
    "GraphitiGraphBuilderService",
    "TextProcessor",
    "GraphitiEntityReader",
    "EntityNode",
    "FilteredEntities",
    "GraphitiGraphMemoryUpdater",
    "GraphitiGraphMemoryManager",
    "MatchSimulator",
    "SimulationResult",
    "Trajectory",
    "Event",
    "RosterSampler",
    "EventNarrativePolisher",
    "AnalystNotesWriter",
    "CoachReviewWriter",
]


def __getattr__(name: str):
    if name == "OntologyGenerator":
        from .ontology_generator import OntologyGenerator
        return OntologyGenerator
    if name == "GraphitiGraphBuilderService":
        from .graphiti_graph_builder import GraphitiGraphBuilderService
        return GraphitiGraphBuilderService
    if name == "TextProcessor":
        from .text_processor import TextProcessor
        return TextProcessor
    if name == "GraphitiEntityReader":
        from .graphiti_entity_reader import GraphitiEntityReader
        return GraphitiEntityReader
    if name in {"EntityNode", "FilteredEntities"}:
        from . import graph_models
        return getattr(graph_models, name)
    if name in {"GraphitiGraphMemoryUpdater", "GraphitiGraphMemoryManager"}:
        from . import graphiti_graph_memory_updater
        return getattr(graphiti_graph_memory_updater, name)
    if name in {"MatchSimulator", "SimulationResult", "Trajectory", "Event"}:
        from . import match_simulator
        return getattr(match_simulator, name)
    if name == "RosterSampler":
        from .roster_sampler import RosterSampler
        return RosterSampler
    if name == "EventNarrativePolisher":
        from .event_narrative_polisher import EventNarrativePolisher
        return EventNarrativePolisher
    if name == "AnalystNotesWriter":
        from .analyst_notes_writer import AnalystNotesWriter
        return AnalystNotesWriter
    if name == "CoachReviewWriter":
        from .coach_review_writer import CoachReviewWriter
        return CoachReviewWriter
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
