FROM python:3.12.12-slim
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*
COPY requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
COPY alembic.ini ./
ENV PYTHONPATH=/app/src PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
RUN useradd --uid 10001 --create-home app
RUN mkdir -p /var/lib/reverse-hr/media /var/lib/reverse-hr/resumes && chown app:app /var/lib/reverse-hr/media /var/lib/reverse-hr/resumes \
    && chmod 700 /var/lib/reverse-hr/media /var/lib/reverse-hr/resumes
RUN mkdir -p /run/pdf /run/decoder && chown app:app /run/pdf /run/decoder && chmod 700 /run/pdf /run/decoder
USER app
EXPOSE 8000
CMD ["uvicorn", "reverse_hr.platform.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
