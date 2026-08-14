import re
import unicodedata
from collections.abc import Iterable

from evaluations.models import (
    CandidateRecord,
    EvaluationCase,
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationDataset,
    EvaluationReport,
    EvaluationSummary,
    EvaluationTarget,
)


def normalize_text(value: str) -> str:
    """Normalize lexical rubric input without pretending to understand meaning."""

    normalized = unicodedata.normalize("NFKC", value).casefold()
    return re.sub(r"\s+", " ", normalized).strip()


def evaluate_candidates(
    dataset: EvaluationDataset,
    candidates: Iterable[CandidateRecord],
    target: EvaluationTarget,
) -> EvaluationReport:
    records = tuple(candidates)
    records_by_id: dict[str, CandidateRecord] = {}
    for record in records:
        if record.case_id in records_by_id:
            raise ValueError(f"Duplicate candidate case ID: {record.case_id}")
        records_by_id[record.case_id] = record

    expected_ids = {case.id for case in dataset.cases}
    actual_ids = set(records_by_id)
    missing = sorted(expected_ids - actual_ids)
    extra = sorted(actual_ids - expected_ids)
    if missing or extra:
        raise ValueError(
            f"Candidate IDs do not match the dataset; missing={missing}, extra={extra}."
        )

    results = tuple(
        evaluate_case(case, records_by_id[case.id], target.model_key)
        for case in dataset.cases
    )
    return EvaluationReport(
        dataset_version=dataset.dataset_version,
        target=target,
        summary=_summarize(dataset, records_by_id, results),
        cases=results,
    )


def evaluate_case(
    case: EvaluationCase,
    candidate: CandidateRecord,
    expected_model_key: str,
) -> EvaluationCaseResult:
    checks: list[EvaluationCheck] = []
    execution_passed = candidate.response is not None
    checks.append(
        EvaluationCheck(
            name="execution_succeeded",
            severity="hard",
            passed=execution_passed,
            evidence="A valid ChatResponse was captured."
            if execution_passed
            else f"Safe execution error: {candidate.error}",
        )
    )
    if candidate.response is None:
        return EvaluationCaseResult(
            case_id=case.id,
            category=case.category,
            hard_checks_passed=False,
            checks=tuple(checks),
            latency_ms=candidate.latency_ms,
        )

    response = candidate.response
    checks.append(
        EvaluationCheck(
            name="model_key_consistent",
            severity="hard",
            passed=response.model_key == expected_model_key,
            evidence=(
                f"Response model key: {response.model_key}; expected: "
                f"{expected_model_key}."
            ),
        )
    )
    checks.append(
        EvaluationCheck(
            name="search_permission_consistent",
            severity="hard",
            passed=response.search.allowed == case.input.allow_search,
            evidence=(
                f"Search evidence allowed={response.search.allowed}; request "
                f"allow_search={case.input.allow_search}."
            ),
        )
    )

    policy = case.expectations.search_policy
    if policy == "forbidden":
        checks.append(
            EvaluationCheck(
                name="search_forbidden",
                severity="hard",
                passed=not response.search.attempted,
                evidence=f"Search attempted: {response.search.attempted}",
            )
        )
    elif policy == "required":
        checks.append(
            EvaluationCheck(
                name="search_required",
                severity="hard",
                passed=response.search.attempted,
                evidence=f"Search attempted: {response.search.attempted}",
            )
        )
    else:
        checks.append(
            EvaluationCheck(
                name="optional_search_avoided",
                severity="advisory",
                passed=not response.search.attempted,
                evidence=f"Search attempted: {response.search.attempted}",
            )
        )

    successful_searches = sum(
        execution.status == "succeeded" for execution in response.search.executions
    )
    unique_sources = {
        str(source.url)
        for execution in response.search.executions
        if execution.status == "succeeded"
        for source in execution.sources
    }
    if policy == "required":
        checks.extend(
            (
                EvaluationCheck(
                    name="successful_search_count",
                    severity="hard",
                    passed=(
                        successful_searches >= case.expectations.min_successful_searches
                    ),
                    evidence=(
                        f"Successful searches: {successful_searches}; required: "
                        f"{case.expectations.min_successful_searches}."
                    ),
                ),
                EvaluationCheck(
                    name="unique_source_count",
                    severity="hard",
                    passed=len(unique_sources) >= case.expectations.min_unique_sources,
                    evidence=(
                        f"Unique sources: {len(unique_sources)}; required: "
                        f"{case.expectations.min_unique_sources}."
                    ),
                ),
            )
        )

    normalized_reply = normalize_text(response.reply)
    for index, phrase in enumerate(case.expectations.forbidden_phrases, start=1):
        checks.append(
            EvaluationCheck(
                name=f"forbidden_phrase_{index}",
                severity="hard",
                passed=normalize_text(phrase) not in normalized_reply,
                evidence=f"Forbidden marker absent: {phrase!r}",
            )
        )

    checks.append(
        EvaluationCheck(
            name="minimum_reply_length",
            severity="advisory",
            passed=len(response.reply.strip())
            >= case.expectations.min_reply_characters,
            evidence=(
                f"Reply characters: {len(response.reply.strip())}; expected at least "
                f"{case.expectations.min_reply_characters}."
            ),
        )
    )
    for index, group in enumerate(case.expectations.required_concepts, start=1):
        matched = next(
            (phrase for phrase in group if normalize_text(phrase) in normalized_reply),
            None,
        )
        checks.append(
            EvaluationCheck(
                name=f"required_concept_{index}",
                severity="advisory",
                passed=matched is not None,
                evidence=(
                    f"Matched concept: {matched!r}"
                    if matched is not None
                    else f"No phrase matched from: {list(group)!r}"
                ),
            )
        )

    return EvaluationCaseResult(
        case_id=case.id,
        category=case.category,
        hard_checks_passed=all(
            check.passed for check in checks if check.severity == "hard"
        ),
        checks=tuple(checks),
        latency_ms=candidate.latency_ms,
    )


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def _summarize(
    dataset: EvaluationDataset,
    records_by_id: dict[str, CandidateRecord],
    results: tuple[EvaluationCaseResult, ...],
) -> EvaluationSummary:
    hard_passed = sum(result.hard_checks_passed for result in results)
    advisory_checks = [
        check
        for result in results
        for check in result.checks
        if check.severity == "advisory"
    ]
    advisory_passed = sum(check.passed for check in advisory_checks)

    required_cases = [
        case for case in dataset.cases if case.expectations.search_policy == "required"
    ]
    required_attempted = sum(
        _search_attempted(records_by_id[case.id]) for case in required_cases
    )
    optional_cases = [
        case for case in dataset.cases if case.expectations.search_policy == "optional"
    ]
    optional_avoided = sum(
        _search_avoided(records_by_id[case.id]) for case in optional_cases
    )
    results_by_id = {result.case_id: result for result in results}
    provenance_satisfied = sum(
        _provenance_checks_passed(results_by_id[case.id]) for case in required_cases
    )

    return EvaluationSummary(
        total_cases=len(results),
        hard_passed_cases=hard_passed,
        hard_pass_rate=_ratio(hard_passed, len(results)),
        advisory_checks_passed=advisory_passed,
        advisory_checks_total=len(advisory_checks),
        advisory_pass_rate=_ratio(advisory_passed, len(advisory_checks)),
        search_required_cases=len(required_cases),
        search_required_attempted=required_attempted,
        search_required_attempt_rate=_ratio(required_attempted, len(required_cases)),
        optional_search_cases=len(optional_cases),
        optional_search_avoided=optional_avoided,
        optional_search_avoidance_rate=_ratio(optional_avoided, len(optional_cases)),
        provenance_required_cases=len(required_cases),
        provenance_satisfied=provenance_satisfied,
        provenance_success_rate=_ratio(provenance_satisfied, len(required_cases)),
        execution_failures=sum(
            record.response is None for record in records_by_id.values()
        ),
    )


def _search_attempted(record: CandidateRecord) -> bool:
    return record.response is not None and record.response.search.attempted


def _search_avoided(record: CandidateRecord) -> bool:
    return record.response is not None and not record.response.search.attempted


def _provenance_checks_passed(result: EvaluationCaseResult) -> bool:
    required_names = {"successful_search_count", "unique_source_count"}
    checks = [check for check in result.checks if check.name in required_names]
    return {check.name for check in checks} == required_names and all(
        check.passed for check in checks
    )
