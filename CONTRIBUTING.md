# Contributing

Thank you for improving this learning-focused project. Changes should remain small enough to review, preserve the typed public contracts, and include evidence that they work without calling paid model or search providers.

## Development setup

1. Use Python 3.12.
2. Install the locked development environment:

   ```powershell
   python -m pipenv sync --dev
   ```

3. Copy `.env.example` to `.env` only when manual provider testing is needed. Never commit credentials.

## Before opening a pull request

Run the same gates enforced by CI:

```powershell
python -m pipenv verify
python -m pipenv run ruff check .
python -m pipenv run ruff format --check .
python -m pipenv run mypy
python -m pipenv run python -m evaluations validate
python -m pipenv run python -m evaluations replay --check-baseline
python -m pipenv run python -m pytest --cov=. --cov-report=term-missing --cov-fail-under=80
```

To apply the formatter locally, run:

```powershell
python -m pipenv run ruff format .
```

## Pull-request expectations

- Explain the problem and why the chosen solution fits this repository.
- Keep behavior changes separate from unrelated cleanup when practical.
- Add or update offline tests for success, failure, and boundary cases.
- Add or update versioned evaluation cases when AI behavior expectations change.
- Treat hard evaluation checks as merge gates and advisory lexical scores as review signals, not proof of answer quality.
- Regenerate a committed replay baseline only after reviewing the dataset, candidate responses, and report diff together.
- Update the README and learning journal when a contract, workflow, or architectural decision changes.
- Call out security, compatibility, migration, and operational implications.
- Do not include secrets, generated caches, provider responses containing private data, or local environment files.

The `main` branch is protected. Changes are merged through pull requests after the required quality, test, deterministic-evaluation, and security checks pass. Live evaluations are manual because they use external providers, may cost money, and cannot be made bit-for-bit repeatable.
