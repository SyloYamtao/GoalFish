"""Migrate legacy report files into prediction report database tables."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import init_db
from app.services.report_agent import ReportManager, ReportOutline, ReportSection


def _load_outline_file(report_dir: Path) -> ReportOutline | None:
    outline_path = report_dir / "outline.json"
    if not outline_path.exists():
        return None

    with outline_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    sections = [
        ReportSection(title=item.get("title", ""), content=item.get("content", "") or "")
        for item in data.get("sections", []) or []
    ]
    return ReportOutline(
        title=data.get("title", "") or "",
        summary=data.get("summary", "") or "",
        sections=sections,
    )


def _parse_section_index(filename: str) -> int | None:
    stem = filename.removesuffix(".md")
    parts = stem.split("_")
    if len(parts) != 2 or parts[0] != "section":
        return None
    try:
        return int(parts[1])
    except ValueError:
        return None


def _extract_section_title(markdown: str, fallback: str) -> str:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            return stripped[3:].strip() or fallback
    return fallback


def _migrate_report_sections(report_id: str, report_dir: Path) -> int:
    section_count = 0
    for section_path in sorted(report_dir.glob("section_*.md")):
        section_index = _parse_section_index(section_path.name)
        if section_index is None:
            continue

        content = section_path.read_text(encoding="utf-8")
        title = _extract_section_title(content, f"section_{section_index:02d}")
        ReportManager._save_section_to_db(
            report_id,
            section_index,
            ReportSection(title=title),
            content,
        )
        section_count += 1
    return section_count


def _load_progress(report_dir: Path) -> dict[str, Any] | None:
    progress_path = report_dir / "progress.json"
    if not progress_path.exists():
        return None
    with progress_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _load_agent_log(report_dir: Path) -> list[dict[str, Any]]:
    log_path = report_dir / "agent_log.jsonl"
    if not log_path.exists():
        return []

    entries: list[dict[str, Any]] = []
    with log_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                item = json.loads(stripped)
            except json.JSONDecodeError:
                item = {"raw": stripped}
            if isinstance(item, dict):
                entries.append(item)
    return entries


def _load_console_log(report_dir: Path) -> list[str]:
    log_path = report_dir / "console_log.txt"
    if not log_path.exists():
        return []
    return [line.rstrip("\n\r") for line in log_path.read_text(encoding="utf-8").splitlines()]


def _migrate_report_runtime_metadata(report_id: str, report_dir: Path) -> dict[str, Any]:
    progress = _load_progress(report_dir) if report_dir.exists() else None
    agent_log = _load_agent_log(report_dir) if report_dir.exists() else []
    console_log = _load_console_log(report_dir) if report_dir.exists() else []

    if progress is None and not agent_log and not console_log:
        return {
            "has_progress": False,
            "agent_log_entries": 0,
            "console_log_lines": 0,
        }

    def updater(metadata: dict[str, Any]) -> None:
        if progress is not None:
            metadata["progress"] = progress
        if agent_log:
            metadata["agent_log"] = agent_log
        if console_log:
            metadata["console_log"] = console_log

    ReportManager._update_report_metadata(report_id, updater)
    return {
        "has_progress": progress is not None,
        "agent_log_entries": len(agent_log),
        "console_log_lines": len(console_log),
    }


def _migrate_report(
    report_id: str,
    *,
    dry_run: bool = False,
    skip_existing: bool = False,
    delete_after_migrate: bool = False,
) -> dict[str, Any]:
    if skip_existing and ReportManager.get_report(report_id):
        return {
            "report_id": report_id,
            "status": "skipped",
            "reason": "already exists",
            "sections": 0,
        }

    report = ReportManager._load_report_from_files(report_id)
    if not report:
        return {
            "report_id": report_id,
            "status": "skipped",
            "reason": "missing meta json",
            "sections": 0,
        }

    report_dir = Path(ReportManager._get_report_folder(report_id))
    if report_dir.exists():
        outline = _load_outline_file(report_dir)
        if outline:
            report.outline = outline

    if dry_run:
        return {
            "report_id": report_id,
            "status": "dry_run",
            "simulation_id": report.simulation_id,
            "report_status": report.status.value,
            "sections": len(list(report_dir.glob("section_*.md"))) if report_dir.exists() else 0,
            "has_markdown": bool(report.markdown_content),
        }

    ReportManager._save_report_to_db(report)
    section_count = _migrate_report_sections(report_id, report_dir) if report_dir.exists() else 0
    runtime_metadata = _migrate_report_runtime_metadata(report_id, report_dir)

    deleted = False
    if delete_after_migrate and report_dir.exists():
        shutil.rmtree(report_dir)
        deleted = True

    return {
        "report_id": report_id,
        "status": "migrated",
        "simulation_id": report.simulation_id,
        "report_status": report.status.value,
        "sections": section_count,
        "has_markdown": bool(report.markdown_content),
        "deleted": deleted,
        **runtime_metadata,
    }


def _discover_report_ids(reports_dir: Path) -> list[str]:
    if not reports_dir.exists():
        return []

    report_ids = set()
    for item in reports_dir.iterdir():
        if item.is_dir() and (item / "meta.json").exists():
            report_ids.add(item.name)
        elif item.is_file() and item.suffix == ".json":
            report_ids.add(item.stem)
    return sorted(report_ids)


def migrate_reports_to_db(
    reports_dir: str | None = None,
    *,
    dry_run: bool = False,
    skip_existing: bool = False,
    delete_after_migrate: bool = False,
) -> list[dict[str, Any]]:
    if reports_dir:
        ReportManager.REPORTS_DIR = reports_dir

    init_db()
    report_ids = _discover_report_ids(Path(ReportManager.REPORTS_DIR))
    return [
        _migrate_report(
            report_id,
            dry_run=dry_run,
            skip_existing=skip_existing,
            delete_after_migrate=delete_after_migrate,
        )
        for report_id in report_ids
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate report files into database tables.")
    parser.add_argument(
        "--reports-dir",
        default=os.environ.get("REPORTS_DIR"),
        help="Report directory. Defaults to Config.UPLOAD_FOLDER/reports.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Preview migrations without writing to the database.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip reports that already exist in the database.")
    parser.add_argument(
        "--delete-after-migrate",
        action="store_true",
        help="Delete each migrated legacy report directory after a successful import.",
    )
    args = parser.parse_args()

    results = migrate_reports_to_db(
        args.reports_dir,
        dry_run=args.dry_run,
        skip_existing=args.skip_existing,
        delete_after_migrate=args.delete_after_migrate,
    )
    migrated = sum(1 for item in results if item["status"] == "migrated")
    skipped = len(results) - migrated
    print(json.dumps({"migrated": migrated, "skipped": skipped, "reports": results}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
