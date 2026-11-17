# Passerelle d'échange (service « mediateur ») : un seul processus qui sert aussi les couches
# consentement-minimisation et journal (un dossier par couche, même processus : voir LIMITES.md).
# Contexte de construction : la RACINE du dépôt (docker-compose.yml : context: ., dockerfile: passerelle/Dockerfile).
FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY passerelle/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY passerelle/app ./app
COPY consentement-minimisation/consentement ./consentement
COPY journal/tracabilite ./tracabilite
RUN useradd --system --uid 10001 griot && mkdir /donnees && chown griot /donnees
USER griot
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
