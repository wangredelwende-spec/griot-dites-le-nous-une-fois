# Conversion UNE SEULE FOIS d'un PDF SCANNÉ en CSV (profil docker « ocr », jamais lancé avec la pile).
# Tesseract (Apache-2.0) + données « fra », poppler-utils / pdftoppm (GPL-2.0), paquets Debian bookworm.
# Construire AVANT la finale (il faut le réseau pour apt) ; ensuite tout fonctionne hors ligne.
FROM python:3.13.5-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-fra poppler-utils \
 && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY convertir.py .
RUN useradd --system --uid 10001 griot
USER griot
ENTRYPOINT ["python", "/app/convertir.py"]
