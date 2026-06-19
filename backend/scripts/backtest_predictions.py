#!/usr/bin/env python3
"""Run football prediction backtests and write calibration metrics."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.services.backtest import PredictionBacktester, WorkflowPredictionRunner  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Step2+Step3 predictions over a football holdout CSV.",
    )
    parser.add_argument(
        "--holdout-csv",
        required=True,
        help="CSV: date,home_iso3,away_iso3,home_score,away_score,knockout,host_iso3,competition",
    )
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--budget", default="middle")
    parser.add_argument("--n-matches", type=int, default=None)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    report = PredictionBacktester(prediction_runner=WorkflowPredictionRunner()).run(
        holdout_csv=Path(args.holdout_csv),
        dataset_id=args.dataset_id,
        budget=args.budget,
        n_matches=args.n_matches,
        output=Path(args.output),
    )
    summary = {
        "output": args.output,
        "n_matches": report["metrics"]["n_matches"],
        "rps": report["metrics"]["rps"],
        "brier": report["metrics"]["brier"],
        "modal_score_hit_rate": report["metrics"]["modal_score_hit_rate"],
    }
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
