FROM python:3.13-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATABASE_PATH=/app/data/licenses.sqlite3
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --uid 10001 --create-home service && mkdir data && chown service:service data
COPY server.py admin_bot.py .
USER service
EXPOSE 8080
CMD ["python", "server.py", "serve"]
