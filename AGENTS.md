# Repository Guidelines

## Project Structure & Module Organization

Prompt Sentinel detects prompt injection through a FastAPI backend and Vue 3 console.

- `backend/app/`: API routes, configuration/authentication, detectors, defense layers, model adapters, database models, and orchestration services. Tests live in `backend/tests/`.
- `frontend/src/`: Vue pages, reusable components, API client, routing, and styles; static assets live in `frontend/public/`.
- `scripts/`: setup, model downloads, dataset preparation, evaluation, and result auditing.
- `docs/`: requirements, architecture diagrams, and acceptance evidence. `deliverables/` contains thesis/presentation artifacts; `results/` preserves experiments. `data/`, `models/`, and `.runtime/` hold datasets, weights, and local state.

## Build, Test, and Development Commands

Use Python 3.11 and Node.js 20.19+ or 22.12+. Run commands from the repository root unless specified.

- `.\start.bat --setup`: install dependencies, prepare models/data, and start services.
- `.\start.bat --check`: validate configuration without starting services.
- `.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000`: start the API with one worker; in-memory sessions and queues require this.
- Inside `frontend/`, run `npm ci`, then `npm run dev` for development or `npm run build` for production validation.

## Coding Style & Naming Conventions

Use four-space Python indentation, `snake_case` functions/modules, `PascalCase` classes, and type annotations. Use two-space frontend indentation, `camelCase` JavaScript identifiers, and `PascalCase.vue` components. Follow `frontend/.prettierrc.json`: single quotes, no semicolons, 100-column width, and ES5 trailing commas. Check changed frontend files with `npx prettier --check <paths>` inside `frontend/`. No Python formatter/linter configuration is present.

## Testing Guidelines

Run `.\.venv\Scripts\python.exe -m pytest -q -m "not integration"`. Name tests `test_*.py` and functions `test_<behavior>`. Use pytest fixtures, temporary databases, and mocked model calls for isolated regressions. Prepare datasets before running `-m integration`; `scripts/smoke_test.py --device cpu` additionally exercises real local models and Ollama. No numeric coverage threshold or frontend test runner is configured.

## Commit & Pull Request Guidelines

No established commit convention is documented; use concise imperative subjects, such as `Fix guard output parsing`. PRs should describe behavior changes, link relevant issues, report validation commands/results, and include screenshots for UI changes.

## Configuration & Evidence

Keep policy settings in `backend/config.yaml` and rules in `backend/rules.yaml`. Keep secrets in environment variables or ignored local state. Preserve existing experiment evidence; use a new `results/<run-name>/` directory.

## Agent Instructions

Use `C:\Program Files\PowerShell\7\pwsh.exe` for Windows commands. If substituted, explicitly invoke it with `& 'C:\Program Files\PowerShell\7\pwsh.exe' -NoLogo -NoProfile -Command { ... }`. Verify `$PSVersionTable.PSVersion` and `(Get-Process -Id $PID).Path` inside that session.
