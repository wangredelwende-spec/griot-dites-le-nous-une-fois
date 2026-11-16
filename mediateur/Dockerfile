# Médiateur : API JSON, réseau interne uniquement
FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# /donnees : journal chaîné + demandes en attente (SQLite)
RUN useradd --system --uid 10001 griot && mkdir /donnees && chown griot /donnees
USER griot
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
