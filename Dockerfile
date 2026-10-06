FROM python:3.12.12-slim
WORKDIR /app
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
COPY migrations ./migrations
COPY alembic.ini ./
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --uid 10001 --create-home app
USER app
EXPOSE 8000
CMD ["uvicorn", "reverse_hr.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
