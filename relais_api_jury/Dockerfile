# Relais vers l'API du jury (profil « api-jury ») : bibliothèque standard Python seulement.
FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY relais.py .
RUN useradd --system --uid 10001 griot
USER griot
CMD ["python", "/app/relais.py"]
