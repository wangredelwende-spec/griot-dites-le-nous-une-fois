# Guichet des agents (FastAPI + Jinja2, rendu serveur)
FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Utilisateur sans privilège ; /donnees contient les données du guichet
RUN useradd --system --uid 10001 guichet && mkdir /donnees && chown guichet /donnees
USER guichet
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
