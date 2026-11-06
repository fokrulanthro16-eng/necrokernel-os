# NecroKernel-OS engine image (stdlib-only runtime; no pip packages needed to serve).
# NOTE: this file was NOT built in the authoring sandbox (no working container runtime there).
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 NECRO_HOST=0.0.0.0
RUN useradd --create-home --uid 10001 necro
WORKDIR /app

FROM base AS test
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "-m", "pytest", "-q", "test_reanimation_cycle.py"]

FROM base AS runtime
COPY engine ./engine
COPY .kiro ./.kiro
USER necro
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s \
  CMD python -c "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=2)"
CMD ["python", "-m", "engine.server"]
