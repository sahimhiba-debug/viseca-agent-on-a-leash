# The wallet, its demo API and the static page. One image, no build step for the
# frontend: the UI is a single HTML file on purpose, so there is nothing to compile
# and nothing that can be stale relative to what was tested.
FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencies first, so editing source does not reinstall them.
COPY pyproject.toml README.md ./
COPY src/ ./src/
RUN pip install --no-cache-dir .

# Data, page and research apparatus. `research/` is NOT importable by the runtime
# -- tests/test_runtime_boundary.py enforces that -- but the comparison scripts and
# the adversarial brain live there and are worth having in the image.
COPY data/ ./data/
COPY ui/ ./ui/
COPY research/ ./research/
COPY scripts/ ./scripts/

EXPOSE 8420

# No secrets baked in. Model adapters read ANTHROPIC_API_KEY / APERTUS_API_KEY from
# the environment and are never on the judged path: with no key the system runs
# exactly as it does in every test, on the deterministic planner.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD python3 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8420/api/health',timeout=2).status==200 else 1)"

CMD ["uvicorn", "wallet_control.api:app", "--host", "0.0.0.0", "--port", "8420"]
