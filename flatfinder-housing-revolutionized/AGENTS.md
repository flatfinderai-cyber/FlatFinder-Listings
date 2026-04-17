# Repository Guidelines

## Project Structure & Module Organization
This workspace contains a Turborepo monorepo in `flatfinder-housing-revolutionized/`.

- `packages/algorithm`: Python affordability engine (core logic)
- `packages/scraper`: Python listing ingestion
- `packages/web`: Next.js dashboard
- `packages/chatbot`: AI assistant integration
- `packages/database`: Supabase schemas/migrations
- `packages/testing`: cross-package tests and QA tooling
- `packages/deployment`: infra/CI-CD configuration
- `packages/docs`: product and technical documentation

Keep new code inside the owning package; avoid cross-package shortcuts.

## Build, Test, and Development Commands
Run commands from `flatfinder-housing-revolutionized/`.

- `npm install`: install monorepo dependencies
- `npx turbo dev`: run package dev tasks in watch mode
- `npx turbo build`: run all package build pipelines
- `npx turbo lint`: run lint tasks for configured packages
- `npx turbo test`: run test tasks across packages
- `docker compose up -d`: start local service dependencies

## Coding Style & Naming Conventions
- Python backend packages (`algorithm`, `scraper`) are preferred for data/logic services.
- Use 4 spaces for Python, 2 spaces for JS/TS/JSON/YAML.
- Name Python modules/functions in `snake_case`; React components in `PascalCase`; variables in `camelCase` for TS/JS.
- Keep CSS custom (no Tailwind) and use HEX colors (`#RRGGBB`).
- Run lint/test before opening a PR.

## Testing Guidelines
- Put package-focused tests under `packages/testing/` and, where needed, alongside package code.
- Name tests by behavior (example: `test_affordability_threshold.py`, `web-search-form.spec.ts`).
- Validate changes with `npx turbo test`; include regression tests for bug fixes.

## Commit & Pull Request Guidelines
Current history uses Conventional Commit style (`docs: ...`, `chore: ...`). Continue with:

- `feat:`, `fix:`, `docs:`, `chore:`, `refactor:`, `test:`

PRs should include:

- clear summary of what changed and why
- linked issue/task (if available)
- test evidence (command output or CI result)
- screenshots for UI updates in `packages/web`

## Security & Configuration Notes
- Never commit secrets; use env files and secret managers.
- Keep infra changes in `packages/deployment` and document required env vars in `packages/docs` or package READMEs.
