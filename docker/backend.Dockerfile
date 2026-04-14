FROM python:3.12-slim

WORKDIR /app

COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/src/ backend/src/

RUN pip install --no-cache-dir ./backend

ENV PYTHONPATH=/app/backend/src

EXPOSE 8000
CMD ["uvicorn", "trek.api:app", "--host", "0.0.0.0", "--port", "8000"]
