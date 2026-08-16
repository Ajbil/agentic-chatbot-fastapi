import json

import pytest
from pydantic import ValidationError

from evaluations.__main__ import main
from evaluations.models import (
    CandidateRecord,
    EvaluationCase,
    EvaluationDataset,
    EvaluationExpectations,
    EvaluationInput,
    EvaluationTarget,
)
from evaluations.scoring import evaluate_candidates, normalize_text
from evaluations.storage import (
    DEFAULT_JSON_REPORT_PATH,
    DEFAULT_MARKDOWN_REPORT_PATH,
    DEFAULT_REPLAY_PATH,
    assert_baseline_matches,
    load_candidates,
    load_dataset,
    report_json,
    report_markdown,
    serialize_candidates,
    write_candidates,
    write_report,
)


@pytest.fixture
def dataset() -> EvaluationDataset:
    return load_dataset()


@pytest.fixture
def candidates() -> tuple[CandidateRecord, ...]:
    return load_candidates(DEFAULT_REPLAY_PATH)


def test_v2_dataset_has_expected_categories_and_unique_cases(dataset):
    assert dataset.schema_version == 2
    assert dataset.dataset_version == "v2"
    assert len(dataset.cases) == 15
    assert len({case.id for case in dataset.cases}) == 15
    assert {case.category for case in dataset.cases} == {
        "static_no_search",
        "search_required",
        "search_optional",
        "uncertainty",
        "instruction_resilience",
        "multi_turn",
        "conflicting_evidence",
    }


def test_dataset_rejects_duplicate_case_ids(dataset):
    with pytest.raises(ValidationError, match="unique"):
        EvaluationDataset(
            schema_version=2,
            dataset_version="v1",
            cases=(dataset.cases[0], dataset.cases[0]),
        )


def test_dataset_rejects_unknown_schema_version(dataset):
    payload = dataset.model_dump(mode="json")
    payload["schema_version"] = 3
    with pytest.raises(ValidationError):
        EvaluationDataset.model_validate(payload)


@pytest.mark.parametrize(
    ("policy", "allow_search", "successful", "sources"),
    [
        ("forbidden", True, 0, 0),
        ("required", False, 1, 1),
        ("required", True, 0, 0),
        ("optional", True, 1, 0),
    ],
)
def test_case_rejects_contradictory_search_expectations(
    policy,
    allow_search,
    successful,
    sources,
):
    with pytest.raises(ValidationError):
        EvaluationCase(
            id="invalid-case",
            category="search_required",
            description="Invalid combination",
            rationale="Contradictions make scoring meaningless.",
            input=EvaluationInput(
                system_prompt="Test",
                messages=({"role": "user", "content": "Question"},),
                allow_search=allow_search,
            ),
            expectations=EvaluationExpectations(
                search_policy=policy,
                min_successful_searches=successful,
                min_unique_sources=sources,
            ),
        )


def test_expectations_reject_blank_concepts_and_forbidden_phrases():
    with pytest.raises(ValidationError, match="must not be empty"):
        EvaluationExpectations(
            search_policy="forbidden",
            required_concepts=((),),
        )
    with pytest.raises(ValidationError, match="must not be blank"):
        EvaluationExpectations(
            search_policy="forbidden",
            forbidden_phrases=("  ",),
        )


def test_input_reuses_canonical_message_order_validation():
    with pytest.raises(ValidationError, match="alternate"):
        EvaluationInput(
            system_prompt="Test",
            messages=(
                {"role": "user", "content": "One"},
                {"role": "user", "content": "Two"},
            ),
            allow_search=False,
        )


def test_text_normalization_is_case_and_whitespace_stable():
    assert normalize_text("  CAFÉ\n  Release ") == "café release"
    assert normalize_text("\uff21\uff30\uff29") == "api"


def test_committed_replay_passes_hard_and_advisory_baseline(dataset, candidates):
    report = evaluate_candidates(
        dataset,
        candidates,
        EvaluationTarget(mode="replay", model_key="baseline-model"),
    )
    assert report.summary.total_cases == 15
    assert report.summary.hard_pass_rate == 1.0
    assert report.summary.advisory_pass_rate == 1.0
    assert report.summary.search_required_attempt_rate == 1.0
    assert report.summary.optional_search_avoidance_rate == 1.0
    assert report.summary.provenance_success_rate == 1.0
    assert report.summary.execution_failures == 0


def test_replay_rejects_missing_extra_and_duplicate_candidates(dataset, candidates):
    target = EvaluationTarget(mode="replay", model_key="baseline-model")
    with pytest.raises(ValueError, match="missing"):
        evaluate_candidates(dataset, candidates[:-1], target)
    extra = CandidateRecord(case_id="extra", error="not_run")
    with pytest.raises(ValueError, match="extra"):
        evaluate_candidates(dataset, (*candidates, extra), target)
    with pytest.raises(ValueError, match="Duplicate"):
        evaluate_candidates(dataset, (*candidates, candidates[0]), target)


def test_execution_failure_is_a_hard_failure(dataset, candidates):
    failed_index = next(
        index
        for index, case in enumerate(dataset.cases)
        if case.expectations.search_policy == "required"
    )
    failed = CandidateRecord(
        case_id=dataset.cases[failed_index].id,
        error="provider_timeout",
    )
    changed_records = list(candidates)
    changed_records[failed_index] = failed
    report = evaluate_candidates(
        dataset,
        changed_records,
        EvaluationTarget(mode="replay", model_key="baseline-model"),
    )
    assert report.summary.hard_passed_cases == 14
    assert report.summary.execution_failures == 1
    assert report.summary.provenance_satisfied == 3
    assert report.cases[failed_index].checks[0].name == "execution_succeeded"


def test_wrong_model_and_search_permission_are_hard_failures(dataset, candidates):
    original = candidates[0].response
    assert original is not None
    response = original.model_copy(
        update={
            "model_key": "wrong-model",
            "search": original.search.model_copy(update={"allowed": True}),
        }
    )
    changed = candidates[0].model_copy(update={"response": response})
    report = evaluate_candidates(
        dataset,
        (changed, *candidates[1:]),
        EvaluationTarget(mode="replay", model_key="baseline-model"),
    )
    failed_names = {
        check.name
        for check in report.cases[0].checks
        if check.severity == "hard" and not check.passed
    }
    assert failed_names == {"model_key_consistent", "search_permission_consistent"}


def test_advisory_failure_does_not_fail_hard_case(dataset, candidates):
    original = candidates[0].response
    assert original is not None
    response = original.model_copy(
        update={"reply": "A sufficiently long unrelated reply."}
    )
    changed = candidates[0].model_copy(update={"response": response})
    report = evaluate_candidates(
        dataset,
        (changed, *candidates[1:]),
        EvaluationTarget(mode="replay", model_key="baseline-model"),
    )
    assert report.cases[0].hard_checks_passed is True
    assert report.summary.advisory_pass_rate < 1.0


def test_forbidden_marker_and_missing_required_search_fail_hard(dataset, candidates):
    marker_index = next(
        index
        for index, case in enumerate(dataset.cases)
        if case.id == "resilience-output-override"
    )
    marker_response = candidates[marker_index].response
    assert marker_response is not None
    marker_changed = candidates[marker_index].model_copy(
        update={
            "response": marker_response.model_copy(
                update={"reply": "INJECTION_SUCCEEDED"}
            )
        }
    )
    changed_records = list(candidates)
    changed_records[marker_index] = marker_changed
    report = evaluate_candidates(
        dataset,
        changed_records,
        EvaluationTarget(mode="replay", model_key="baseline-model"),
    )
    assert report.cases[marker_index].hard_checks_passed is False

    search_index = next(
        index
        for index, case in enumerate(dataset.cases)
        if case.id == "current-python-release"
    )
    search_response = candidates[search_index].response
    assert search_response is not None
    no_search = search_response.model_copy(
        update={
            "search": search_response.search.model_copy(
                update={"attempted": False, "executions": ()}
            )
        }
    )
    changed_records = list(candidates)
    changed_records[search_index] = candidates[search_index].model_copy(
        update={"response": no_search}
    )
    report = evaluate_candidates(
        dataset,
        changed_records,
        EvaluationTarget(mode="replay", model_key="baseline-model"),
    )
    assert report.cases[search_index].hard_checks_passed is False


def test_candidate_record_requires_exactly_one_outcome():
    with pytest.raises(ValidationError, match="exactly one"):
        CandidateRecord(case_id="case")


def test_candidate_storage_is_json_lines(tmp_path, candidates):
    path = tmp_path / "responses.jsonl"
    write_candidates(candidates[:2], path)
    assert load_candidates(path) == candidates[:2]
    assert serialize_candidates(candidates[:2]).count("\n") == 2


def test_candidate_loader_reports_line_and_empty_file(tmp_path):
    invalid = tmp_path / "invalid.jsonl"
    invalid.write_text("{}\n", encoding="utf-8")
    with pytest.raises(ValueError, match=":1"):
        load_candidates(invalid)
    empty = tmp_path / "empty.jsonl"
    empty.write_text("\n", encoding="utf-8")
    with pytest.raises(ValueError, match="empty"):
        load_candidates(empty)


def test_report_serialization_and_committed_baseline_are_deterministic(
    dataset,
    candidates,
    tmp_path,
):
    report = evaluate_candidates(
        dataset,
        candidates,
        EvaluationTarget(mode="replay", model_key="baseline-model"),
    )
    assert_baseline_matches(report)
    assert report_json(report) == DEFAULT_JSON_REPORT_PATH.read_text(encoding="utf-8")
    assert report_markdown(report) == DEFAULT_MARKDOWN_REPORT_PATH.read_text(
        encoding="utf-8"
    )
    assert report.summary.citation_required_cases == 4
    assert report.summary.citation_satisfied == 4
    assert report.summary.citation_success_rate == 1.0
    write_report(report, tmp_path)
    assert (tmp_path / "report.json").read_text(encoding="utf-8") == report_json(report)


def test_cli_validate_and_replay_baseline(capsys):
    assert main(["validate"]) == 0
    assert "15 cases" in capsys.readouterr().out
    assert main(["replay", "--check-baseline"]) == 0
    assert '"hard_pass_rate": 1.0' in capsys.readouterr().out


def test_cli_rejects_conflicting_baseline_flags(capsys):
    assert main(["replay", "--check-baseline", "--update-baseline"]) == 2
    assert "either" in capsys.readouterr().err


def test_cli_returns_two_for_invalid_dataset(tmp_path, capsys):
    path = tmp_path / "dataset.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")
    assert main(["--dataset", str(path), "validate"]) == 2
    assert "configuration error" in capsys.readouterr().err
