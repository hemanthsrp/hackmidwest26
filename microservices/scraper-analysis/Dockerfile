FROM python:3.12-slim
WORKDIR /app
COPY microservices/scraper-analysis/pyproject.toml ./pyproject.toml
COPY microservices/scraper-analysis/src ./src
RUN pip install --no-cache-dir . && useradd --system --uid 10001 app
USER app
EXPOSE 8001
CMD ["uvicorn", "scraper_analysis.api:app", "--host", "0.0.0.0", "--port", "8001"]
