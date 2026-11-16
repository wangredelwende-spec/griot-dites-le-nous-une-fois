# Registre simulé (un seul code ; l'instance est choisie par la variable ADAPTATEUR)
FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Utilisateur sans privilège (même uid dans toutes nos images : le volume partagé des clés publiques
# lui appartient). /cles : clé privée de CE registre ; /publiques : clés publiques de tous les registres.
RUN useradd --system --uid 10001 griot && mkdir /cles /publiques && chown griot /cles /publiques
USER griot
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
