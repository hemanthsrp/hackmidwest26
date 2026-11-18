FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /app
# Exact third-party versions, the same ones CI tests (scripts/lock-python.sh).
COPY requirements/python.lock /app/python.lock
COPY microservices/scraper-analysis/pyproject.toml /app/scraper-analysis/pyproject.toml
COPY microservices/scraper-analysis/src /app/scraper-analysis/src
COPY microservices/agentic-search /app/agentic-search
COPY microservices/jev-tool /app/jev-tool
RUN pip install --no-cache-dir -c /app/python.lock /app/agentic-search /app/jev-tool /app/scraper-analysis \
    && useradd --system --uid 10001 app
USER app
EXPOSE 8001
CMD ["uvicorn", "scraper_analysis.api:app", "--host", "0.0.0.0", "--port", "8001"]
