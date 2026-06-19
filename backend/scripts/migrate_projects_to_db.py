"""Migrate legacy file-based projects into the configured database.

Run from the repository root or backend directory:

    uv run python scripts/migrate_projects_to_db.py
    uv run python scripts/migrate_projects_to_db.py --delete-after-migrate

The script reads legacy directories under backend/uploads/projects by default.
It writes project metadata and extracted text to the projects table selected by
DATABASE_URL. Raw uploaded files are not imported because the application now
uses extracted_text from the database for downstream graph/simulation steps.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import traceback
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Config  # noqa: E402
from app.models.project import Project, ProjectManager  # noqa: E402


def _default_legacy_projects_dir() -> Path:
    return Path(Config.UPLOAD_FOLDER).resolve() / "projects"


def migrate_projects(
    legacy_projects_dir: Path,
    *,
    delete_after_migrate: bool = False,
    skip_existing: bool = False,
    dry_run: bool = False,
) -> dict[str, int]:
    summary = {
        "scanned": 0,
        "migrated": 0,
        "skipped": 0,
        "failed": 0,
        "deleted": 0,
    }

    if not legacy_projects_dir.exists():
        print(f"Legacy projects directory does not exist: {legacy_projects_dir}")
        return summary

    for project_dir in sorted(path for path in legacy_projects_dir.iterdir() if path.is_dir()):
        meta_path = project_dir / "project.json"
        if not meta_path.exists():
            continue

        summary["scanned"] += 1
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            project = Project.from_dict(data)

            existing = ProjectManager.get_project(project.project_id) if skip_existing else None
            if existing:
                summary["skipped"] += 1
                print(f"SKIP existing project: {project.project_id}")
                continue

            text_path = project_dir / "extracted_text.txt"
            extracted_text = text_path.read_text(encoding="utf-8") if text_path.exists() else None

            if dry_run:
                print(f"DRY-RUN migrate project: {project.project_id}")
            else:
                ProjectManager.save_project(project, touch_updated_at=False)
                if extracted_text is not None:
                    ProjectManager.save_extracted_text(
                        project.project_id,
                        extracted_text,
                        touch_updated_at=False,
                    )
                summary["migrated"] += 1
                print(f"MIGRATED project: {project.project_id}")

                if delete_after_migrate:
                    shutil.rmtree(project_dir)
                    summary["deleted"] += 1
                    print(f"DELETED legacy project directory: {project_dir}")
        except Exception as exc:
            summary["failed"] += 1
            print(f"FAILED project directory: {project_dir}: {exc}")
            traceback.print_exc()

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy-projects-dir",
        type=Path,
        default=_default_legacy_projects_dir(),
        help="Directory containing legacy project subdirectories.",
    )
    parser.add_argument(
        "--delete-after-migrate",
        action="store_true",
        help="Delete each legacy project directory after it is migrated successfully.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Do not overwrite projects that already exist in the database.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print projects that would be migrated without writing to the database.",
    )
    args = parser.parse_args()

    summary = migrate_projects(
        args.legacy_projects_dir.resolve(),
        delete_after_migrate=args.delete_after_migrate,
        skip_existing=args.skip_existing,
        dry_run=args.dry_run,
    )
    print(f"Summary: {summary}")
    return 1 if summary["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
