FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DB_PATH=/data/lpscout.db
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY lpscout ./lpscout
RUN useradd -m bot && mkdir /data && chown bot /data
USER bot
VOLUME /data
CMD ["python", "-m", "lpscout"]
