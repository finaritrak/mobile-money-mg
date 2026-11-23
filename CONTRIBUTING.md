# Contributing

Thanks for helping! Issues and pull requests are welcome, in English or French.

## Setup

```bash
git clone https://github.com/finaritrak/mobile-money-mg
cd mobile-money-mg
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
```

## Before opening a pull request

```bash
ruff check . && ruff format . && mypy && pytest --cov
```

- Add a test for every behaviour change. HTTP calls are mocked with `httpx.MockTransport`
  (see `tests/conftest.py`) — tests must never hit a real operator.
- **Never commit credentials**, real customer numbers or real transaction IDs.
- If an operator changed its API, link the official documentation in the PR.

## Releasing (maintainers)

1. Bump `version` in `pyproject.toml` and `__version__` in `src/mobile_money_mg/__init__.py`.
2. Update `CHANGELOG.md`.
3. Create a GitHub Release `vX.Y.Z` → the *Publish to PyPI* workflow uploads the package.

One-time setup: on pypi.org → *Your projects → Publishing → Add a new pending publisher*,
with owner `finaritrak`, repository `mobile-money-mg`, workflow `publish.yml`, environment `pypi`.
