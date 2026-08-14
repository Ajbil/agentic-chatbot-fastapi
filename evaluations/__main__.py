import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError

from evaluations.live import (
    LiveEvaluationError,
    run_live_cases,
    select_cases,
    validate_live_target,
)
from evaluations.models import EvaluationTarget
from evaluations.scoring import evaluate_candidates
from evaluations.storage import (
    DEFAULT_DATASET_PATH,
    DEFAULT_REPLAY_PATH,
    assert_baseline_matches,
    load_candidates,
    load_dataset,
    report_json,
    write_baseline_report,
    write_candidates,
    write_report,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate and run deterministic chatbot evaluations."
    )
    parser.add_argument(
        "--dataset",
        type=Path,
        default=DEFAULT_DATASET_PATH,
        help="Versioned evaluation dataset JSON file.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("validate", help="Validate the dataset and exit.")

    replay = subparsers.add_parser(
        "replay",
        help="Score committed or supplied candidate responses.",
    )
    replay.add_argument("--responses", type=Path, default=DEFAULT_REPLAY_PATH)
    replay.add_argument("--check-baseline", action="store_true")
    replay.add_argument("--update-baseline", action="store_true")
    replay.add_argument("--output-dir", type=Path)

    live = subparsers.add_parser(
        "live",
        help="Run paid, nondeterministic cases through a running FastAPI backend.",
    )
    live.add_argument("--model-key", required=True)
    live.add_argument("--confirm-live", action="store_true")
    live.add_argument("--case-id", action="append", default=[])
    live.add_argument("--backend-url", default="http://127.0.0.1:3003")
    live.add_argument("--timeout-seconds", type=float, default=180.0)
    live.add_argument("--output-dir", type=Path)
    live.add_argument("--git-commit", default=os.getenv("GITHUB_SHA", "unknown"))
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        dataset = load_dataset(args.dataset)
        if args.command == "validate":
            print(
                f"Dataset {dataset.dataset_version} is valid "
                f"with {len(dataset.cases)} cases."
            )
            return 0
        if args.command == "replay":
            if args.check_baseline and args.update_baseline:
                raise ValueError(
                    "Choose either --check-baseline or --update-baseline, not both."
                )
            report = evaluate_candidates(
                dataset,
                load_candidates(args.responses),
                EvaluationTarget(mode="replay", model_key="baseline-model"),
            )
            if args.check_baseline:
                assert_baseline_matches(report)
            if args.update_baseline:
                write_baseline_report(report)
            if args.output_dir is not None:
                write_report(report, args.output_dir)
            print(report_json(report), end="")
            return 0 if report.summary.hard_passed_cases == len(report.cases) else 1
        return _run_live(args, dataset)
    except (OSError, ValueError, ValidationError, LiveEvaluationError) as exc:
        print(f"Evaluation configuration error: {exc}", file=sys.stderr)
        return 2


def _run_live(args: argparse.Namespace, dataset: object) -> int:
    from evaluations.models import EvaluationDataset

    if not isinstance(dataset, EvaluationDataset):
        raise LiveEvaluationError("The evaluation dataset type is invalid.")
    if not args.confirm_live:
        raise LiveEvaluationError(
            "Live evaluation may spend provider credits; pass --confirm-live."
        )
    if args.timeout_seconds <= 0 or args.timeout_seconds > 600:
        raise LiveEvaluationError("Live timeout must be between 0 and 600 seconds.")

    selected = select_cases(dataset, args.case_id)
    validate_live_target(args.backend_url, args.model_key, args.timeout_seconds)
    records = run_live_cases(
        selected,
        args.backend_url,
        args.model_key,
        args.timeout_seconds,
    )
    selected_dataset = EvaluationDataset(
        schema_version=dataset.schema_version,
        dataset_version=dataset.dataset_version,
        cases=selected,
    )
    generated_at = datetime.now(UTC).isoformat()
    report = evaluate_candidates(
        selected_dataset,
        records,
        EvaluationTarget(
            mode="live",
            model_key=args.model_key,
            git_commit=args.git_commit,
            generated_at_utc=generated_at,
        ),
    )
    output_dir = args.output_dir or Path("evaluation-results") / (
        f"{dataset.dataset_version}-{args.model_key}-{generated_at.replace(':', '-')}"
    )
    write_report(report, output_dir)
    write_candidates(records, output_dir / "responses.jsonl")
    print(f"Live evaluation report written to {output_dir}")
    return 0 if report.summary.hard_passed_cases == len(report.cases) else 1


if __name__ == "__main__":
    raise SystemExit(main())
