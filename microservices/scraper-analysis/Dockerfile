FROM python:3.12-slim
WORKDIR /app
COPY microservices/scraper-analysis/pyproject.toml /app/scraper-analysis/pyproject.toml
COPY microservices/scraper-analysis/src /app/scraper-analysis/src
COPY microservices/agentic-search /app/agentic-search
COPY microservices/jev-tool /app/jev-tool
RUN pip install --no-cache-dir /app/agentic-search /app/jev-tool /app/scraper-analysis \
    && useradd --system --uid 10001 app
USER app
EXPOSE 8001
CMD ["uvicorn", "scraper_analysis.api:app", "--host", "0.0.0.0", "--port", "8001"]
