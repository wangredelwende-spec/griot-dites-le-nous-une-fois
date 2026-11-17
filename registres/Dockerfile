# Registre simulé (un seul code ; l'instance est choisie par la variable ADAPTATEUR)
# Contexte de construction : la RACINE du dépôt (docker-compose.yml : context: ., dockerfile: registres/Dockerfile),
# pour embarquer le calcul des attributs de la couche consentement-minimisation (regles_attributs/).
FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY registres/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY registres/app ./app
# Minimisation : la fiche reste dans CE conteneur, seule la réponse minimale en sort
COPY consentement-minimisation/regles_attributs ./regles_attributs
# Utilisateur sans privilège. /cles : clé privée de CE registre ;
# /publique : sa clé publique (volume monté en lecture seule chez le médiateur et le guichet) ;
# /trace : sa liste des réponses signées (double trace), à lui seul.
RUN useradd --system --uid 10001 griot && mkdir /cles /publique /trace && chown griot /cles /publique /trace
USER griot
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
