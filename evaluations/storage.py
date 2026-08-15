import json
from collections.abc import Iterable
from pathlib import Path

from evaluations.models import (
    CandidateRecord,
    EvaluationDataset,
    EvaluationReport,
)

PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_DATASET_PATH = PACKAGE_ROOT / "datasets" / "v1.json"
DEFAULT_REPLAY_PATH = PACKAGE_ROOT / "baselines" / "v1-responses.jsonl"
DEFAULT_JSON_REPORT_PATH = PACKAGE_ROOT / "baselines" / "v1-report.json"
DEFAULT_MARKDOWN_REPORT_PATH = PACKAGE_ROOT / "baselines" / "v1-report.md"


def load_dataset(path: Path = DEFAULT_DATASET_PATH) -> EvaluationDataset:
    return EvaluationDataset.model_validate_json(path.read_text(encoding="utf-8"))


def load_candidates(path: Path) -> tuple[CandidateRecord, ...]:
    records: list[CandidateRecord] = []
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(),
        start=1,
    ):
        if not line.strip():
            continue
        try:
            records.append(CandidateRecord.model_validate_json(line))
        except ValueError as exc:
            raise ValueError(
                f"Invalid candidate record at {path}:{line_number}."
            ) from exc
    if not records:
        raise ValueError(f"Candidate file is empty: {path}")
    return tuple(records)


def serialize_candidates(records: Iterable[CandidateRecord]) -> str:
    return "".join(record.model_dump_json() + "\n" for record in records)


def report_json(report: EvaluationReport) -> str:
    return report.model_dump_json(indent=2) + "\n"


def report_markdown(report: EvaluationReport) -> str:
    summary = report.summary
    lines = [
        f"# Evaluation Report — {report.dataset_version}",
        "",
        f"- Mode: `{report.target.mode}`",
        f"- Model: `{report.target.model_key}`",
        f"- Hard case pass rate: {summary.hard_passed_cases}/{summary.total_cases} "
        f"({summary.hard_pass_rate:.2%})",
        f"- Advisory check pass rate: "
        f"{summary.advisory_checks_passed}/{summary.advisory_checks_total} "
        f"({summary.advisory_pass_rate:.2%})",
        f"- Required-search attempt rate: "
        f"{summary.search_required_attempted}/{summary.search_required_cases} "
        f"({summary.search_required_attempt_rate:.2%})",
        f"- Optional-search avoidance rate: "
        f"{summary.optional_search_avoided}/{summary.optional_search_cases} "
        f"({summary.optional_search_avoidance_rate:.2%})",
        f"- Provenance success rate: "
        f"{summary.provenance_satisfied}/{summary.provenance_required_cases} "
        f"({summary.provenance_success_rate:.2%})",
        f"- Execution failures: {summary.execution_failures}",
        "",
        "## Case results",
        "",
        "| Case | Category | Hard checks | Advisory checks |",
        "|---|---|---:|---:|",
    ]
    for result in report.cases:
        advisory = [check for check in result.checks if check.severity == "advisory"]
        advisory_passed = sum(check.passed for check in advisory)
        lines.append(
            f"| `{result.case_id}` | {result.category} | "
            f"{'PASS' if result.hard_checks_passed else 'FAIL'} | "
            f"{advisory_passed}/{len(advisory)} |"
        )

    lines.extend(
        (
            "",
            "## Interpretation",
            "",
            "Hard checks are deterministic repository invariants. Advisory checks use "
            "lexical proxies and do not prove factual correctness, helpfulness, or "
            "claim-level grounding.",
            "",
        )
    )
    return "\n".join(lines)


def write_report(report: EvaluationReport, directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.json").write_text(report_json(report), encoding="utf-8")
    (directory / "report.md").write_text(
        report_markdown(report),
        encoding="utf-8",
    )


def write_candidates(records: Iterable[CandidateRecord], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(serialize_candidates(records), encoding="utf-8")


def assert_baseline_matches(report: EvaluationReport) -> None:
    expected_json = DEFAULT_JSON_REPORT_PATH.read_text(encoding="utf-8")
    expected_markdown = DEFAULT_MARKDOWN_REPORT_PATH.read_text(encoding="utf-8")
    if report_json(report) != expected_json:
        raise ValueError("Generated JSON report does not match the committed baseline.")
    if report_markdown(report) != expected_markdown:
        raise ValueError(
            "Generated Markdown report does not match the committed baseline."
        )


def write_baseline_report(report: EvaluationReport) -> None:
    DEFAULT_JSON_REPORT_PATH.write_text(report_json(report), encoding="utf-8")
    DEFAULT_MARKDOWN_REPORT_PATH.write_text(
        report_markdown(report),
        encoding="utf-8",
    )


def read_json_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object in {path}.")
    return payload
