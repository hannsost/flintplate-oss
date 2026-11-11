# Contributing to FlintPlate

Thanks for your interest in improving FlintPlate! This document explains how to propose changes.

## Ground rules

- Be respectful — this project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
- Never commit secrets, real customer data, personal data or production configuration.
  Use placeholders and the provided `*.example` files.
- Report security vulnerabilities privately (see [SECURITY.md](SECURITY.md)).

## Development workflow

1. Fork the repository and create a topic branch from `main` (`feat/…`, `fix/…`, `docs/…`).
2. Make focused commits with clear messages (Conventional Commits are appreciated, e.g. `fix(api): handle empty payload`).
3. Add or update tests for behaviour changes.
4. Run the checks locally before opening a pull/merge request:

```sh
cd backend
black --check --line-length 100 .
ruff check .
mypy app
python -m unittest discover -s unit_tests
# Full tests require an isolated PostgreSQL + Redis environment; see docs/CONFIGURATION.md.
cd ../frontend && npm ci && npm run lint && npm run build && npm run typecheck
```

5. Open a pull request (GitHub) or merge request (GitLab) and describe *what* and *why*.
   Link related issues. CI must be green before review.

The MCP server has its own dependency-free tests: `cd mcp && npm test`.

## Coding style

Python: Black + Ruff + mypy. TypeScript: strict mode, keep components small and accessible.

## Licensing of contributions

By contributing you agree that your contributions are licensed under the project's [MIT License](LICENSE).
