FROM python:3.12-slim
WORKDIR /app
COPY microservices/scraper-analysis/pyproject.toml ./pyproject.toml
COPY microservices/scraper-analysis/src ./src
COPY microservices/agentic-search/pyproject.toml /app/agentic-search/pyproject.toml
COPY microservices/agentic-search/src /app/agentic-search/src
RUN pip install --no-cache-dir /app/agentic-search . && useradd --system --uid 10001 app
USER app
EXPOSE 8001
CMD ["uvicorn", "scraper_analysis.api:app", "--host", "0.0.0.0", "--port", "8001"]
