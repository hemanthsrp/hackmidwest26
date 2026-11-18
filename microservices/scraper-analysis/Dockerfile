FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
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
