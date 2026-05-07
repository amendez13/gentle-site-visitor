FROM python:3.10-slim-bookworm AS python310
FROM python:3.11-slim-bookworm AS python311

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        curl \
        git \
        gnupg \
        jq \
    && rm -rf /var/lib/apt/lists/*

COPY --from=python310 /usr/local /opt/python/3.10
COPY --from=python311 /usr/local /opt/python/3.11

RUN ln -s /opt/python/3.10/bin/python3.10 /usr/local/bin/python3.10 \
    && ln -s /opt/python/3.11/bin/python3.11 /usr/local/bin/python3.11

COPY requirements.txt /tmp/requirements.txt

RUN set -eux; \
    for py in python3.10 python3.11 python3.12; do \
      "$py" -m pip install --no-cache-dir \
        black==26.3.1 \
        isort==5.13.2 \
        flake8==7.0.0 \
        mypy==1.8.0 \
        types-PyYAML \
        bandit==1.7.6 \
        pip-audit==2.7.3 \
        pytest==9.0.3 \
        pytest-cov==7.1.0 \
        pytest-mock==3.15.1 \
        PyYAML; \
      "$py" -m pip install --no-cache-dir -r /tmp/requirements.txt; \
    done

RUN useradd --create-home --uid 1001 --shell /bin/bash ci \
    && mkdir -p /workspace \
    && chown -R ci:ci /workspace

WORKDIR /workspace
USER ci
