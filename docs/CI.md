# CI/CD Pipeline Documentation

This document describes the Continuous Integration pipeline for gentle-site-visitor, including the Docker CI image, runner-resolution workflow, secret scanning workflow, and the local validation path that mirrors GitHub Actions.

## Overview

The CI workflow runs on pushes and pull requests targeting `main` and `develop`. It now uses a shared Docker image for the real checks instead of installing tools independently in every job.

## CI Jobs (`.github/workflows/ci.yml`)

### Runner Resolution

- `resolve-runner` decides which runner labels downstream jobs should use.
- The default target comes from `github_hosted`.
- Manual `workflow_dispatch` runs can override the target with:
  - `github_hosted`
  - `self_hosted_linux`
  - `self_hosted_linux_arm64`
- Downstream jobs use `runs-on: ${{ fromJSON(needs.resolve-runner.outputs.runner) }}`.
- `resolve-runner` also emits `container.options`; GitHub-hosted runs use root so Playwright can install browser system dependencies, while self-hosted runs keep workspace file ownership compatible with the runner user.

### Smart Skip Logic

`resolve-runner` classifies whether the expensive jobs should be skipped before checking out the repository:

- docs-only changes matching `docs/**`, `notes/**`, `README.md`, `AGENTS.md`, or `CLAUDE.md`
- push-to-`main` commits that GitHub already associates with a merged pull request
- merge-commit fallback heuristic when the API association is temporarily unavailable

The aggregate `CI Status Check` job still runs and reports the skip reason, so the skip path is explicit rather than a silent green pass.

### Container Execution Model

All CI jobs except `resolve-runner` execute in the same image:

- `ghcr.io/${{ github.repository_owner }}/gentle-site-visitor-ci:latest`
- multi-platform manifest: `linux/amd64` and `linux/arm64`
- checkout path isolation via `path: repo`
- `safe.directory` configured in every container job
- no per-job `actions/setup-python`
- Python matrix jobs call preinstalled interpreters directly (`python3.10`, `python3.11`, `python3.12`)
- coverage and test jobs install the checked-out `requirements-dev.txt`, then install Playwright Chromium with its system dependencies before running pytest, so dependency changes in a PR are tested even before the shared image is rebuilt
- the CI image includes `gnupg` because `codecov/codecov-action@v6` verifies the Codecov CLI before uploading coverage

### Failure Short-Circuiting

- workflow concurrency cancels stale pull-request runs on new pushes
- `coverage` runs before the Python matrix, so low coverage fails before the full matrix fan-out
- the Python matrix uses `fail-fast: true`
- each container job requests workflow cancellation via the Actions API if it fails

## Job Summary

### 1. Resolve Runner Target

Purpose: choose the runner labels, container options, CI image reference, and skip mode.

### 2. Lint and Code Quality

Purpose: run black, isort, flake8, and mypy.

Implementation detail:
- uses a pinned lint-only virtual environment so lint versions stay stable even if the shared image tag moves forward

### 3. Coverage Check

Purpose: enforce the `95%` coverage gate, publish the HTML coverage artifact,
and upload `coverage.xml` to Codecov.

The Codecov upload is part of the required coverage job. Upload failures fail
the job so the README coverage badge cannot silently drift to `unknown`.

Private repositories require a repository-level GitHub Actions secret named
`CODECOV_TOKEN`. Public repositories may use Codecov tokenless uploads when
Codecov allows them, but keeping the secret configured is still acceptable.
Create or rotate the secret from a local shell without printing the token:

```bash
gh secret set CODECOV_TOKEN --repo amendez13/gentle-site-visitor
```

The coverage job checks for the secret before invoking Codecov when GitHub
reports the repository as private. It also installs `gnupg` on root-based
GitHub-hosted runs if the shared image has not been rebuilt yet; self-hosted
runs should use an image rebuilt from `infra/ci/Dockerfile`.

### 4. Test Python 3.10 / 3.11 / 3.12

Purpose: run the correctness matrix after the coverage gate passes.

### 5. Security Checks

Purpose: run bandit and pip-audit in the shared CI image.

### 6. Secret Scanning

Purpose: scan repository history for committed secrets with a pinned Gitleaks binary.

Implementation detail:
- runs in `.github/workflows/gitleaks.yml` on push, pull request, and manual dispatch
- checks out full history with `fetch-depth: 0`
- verifies the downloaded Gitleaks archive by SHA-256 before installation
- uploads a redacted SARIF report as both a Code Scanning upload, when supported, and a workflow artifact

### 7. Validate Configuration

Purpose: validate YAML configuration and Python syntax.

### 8. CI Status Check

Purpose: aggregate job outcomes and publish the final required status, including intentional skip reasons.

## Secret Scanning Workflow (`.github/workflows/gitleaks.yml`)

The secret scanning workflow is intentionally separate from the containerized CI
workflow so it runs even when the main CI workflow takes a docs-only skip path.
It scans the full git history with Gitleaks and fails the `Secret Scanning`
check when a potential secret is detected.

The workflow uses:

- `gitleaks git . --redact=100`
- SARIF output at `gitleaks.sarif`
- `github/codeql-action/upload-sarif` with `continue-on-error` for repositories
  where Code Scanning upload is unavailable
- an uploaded `gitleaks-sarif` artifact for review

## CI Image Workflow (`.github/workflows/ci-image.yml`)

The CI image workflow rebuilds and publishes the shared image when these inputs change:

- `infra/ci/Dockerfile`
- `requirements.txt`
- `.pre-commit-config.yaml`

Published tags:

- `ghcr.io/${{ github.repository_owner }}/gentle-site-visitor-ci:latest`
- `ghcr.io/${{ github.repository_owner }}/gentle-site-visitor-ci:<git-sha>`

Published platforms:

- `linux/amd64`
- `linux/arm64`

## Local Validation

### Run the same CI image locally

```bash
docker build -t gentle-site-visitor-ci:test -f infra/ci/Dockerfile .
docker compose -f infra/ci/docker-compose.ci.yml run --rm ci bash
```

Inside the container shell:

```bash
python3.10 --version
python3.11 --version
python3.12 --version
black --version
flake8 --version
mypy --version
pytest --version
python3.12 -m pytest tests/ -v --cov=src
```

### Run the repository checks without Docker

```bash
pre-commit run --all-files
pytest tests/ -v --cov=src --cov-report=term-missing --cov-fail-under=95
pytest tests/ -v
bandit -r src/ -ll
pip-audit --requirement requirements.txt
scripts/security/run-gitleaks.sh
```

## Containerized CI Architecture

```mermaid
flowchart LR
    A["push / pull_request / workflow_dispatch"] --> B["resolve-runner"]
    B --> B1{"merged PR push or docs-only diff?"}
    B1 -- Yes --> H["CI Status Check"]
    B1 -- No --> C["containerized jobs"]
    C --> D["Coverage Check"]
    C --> E["Lint / Security / Validate Configuration"]
    D --> F["Test matrix: Python 3.10 / 3.11 / 3.12"]
    D --> G["coverage.xml + htmlcov + required Codecov upload"]
    E --> H
    F --> H
    G --> H

    I["ci-image.yml"] --> J["Build ghcr.io/${{ github.repository_owner }}/gentle-site-visitor-ci"]
    J --> K["linux/amd64 + linux/arm64"]
    K --> L["latest + sha tags"]
    L --> C
```

## Configuration Files

| File | Purpose |
|------|---------|
| `.github/workflows/ci.yml` | Main CI workflow |
| `.github/workflows/gitleaks.yml` | Secret scanning workflow |
| `.github/workflows/ci-image.yml` | CI image build/publish workflow |
| `infra/ci/Dockerfile` | Shared CI image definition |
| `infra/ci/docker-compose.ci.yml` | Local container shell matching CI |
| `infra/ci/build-and-push.sh` | Manual multi-arch build/push helper |
| `scripts/security/run-gitleaks.sh` | Local pinned Gitleaks bootstrap and scan |
| `docs/CI_RUNNER.md` | Self-hosted runner operations guidance |
| `.pre-commit-config.yaml` | Local pre-commit checks |
| `pyproject.toml` | Tool configurations |
