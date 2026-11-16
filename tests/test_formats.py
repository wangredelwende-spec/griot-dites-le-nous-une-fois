"""Données du jury, format inconnu : PREUVE que tout se règle dans le YAML, sans changer le code.

Les fichiers de tests/donnees_formats (fabriqués par fabriquer.py) contiennent les mêmes personnes fictives
écrites autrement ; chaque YAML de tests/adaptateurs_formats les décrit. Les réponses doivent être les mêmes.
"""
import importlib
import json
import threading
import time
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from conftest import RACINE, TMP

adaptateur = importlib.import_module("registre_app.adaptateur")
DONNEES = RACINE / "tests/donnees_formats"
YAML = RACINE / "tests/adaptateurs_formats"
MAJEUR = {"min": 18, "date_reference": date(2026, 11, 16).isoformat()}


def charger(nom: str, **remplacements) -> "adaptateur.Adaptateur":
    """Le YAML d'essai, avec « /donnees/ » remplacé par le dossier des jeux d'essai (comme le volume Docker)."""
    texte = (YAML / nom).read_text(encoding="utf-8").replace("/donnees/", DONNEES.as_posix() + "/")
    for ancien, nouveau in remplacements.items():
        texte = texte.replace(ancien, nouveau)
    chemin = TMP / nom
    chemin.write_text(texte, encoding="utf-8")
    return adaptateur.Adaptateur(chemin)


def majeur(registre, sujet: str):
    try:
        return registre.calculer("age_entre", sujet, MAJEUR)["age_equal_or_over"]["18"]
    except adaptateur.Refus as motif:
        return f"refus : {motif}"


ATTENDU_ETAT_CIVIL = {
    "BF-0001": True,                                            # 14/03/2001
    "BF-0003": False,                                           # mineure
    "BF-0004": "refus : donnée insuffisante",                   # « vers 1990 »
    "BF-0007": "refus : personne décédée",
    "BF-0011": True,                                            # « 2004 » : année seule, mais concluante
    "BF-0019": "refus : identité ambiguë",                      # deux fiches
    "BF-0099": "refus : introuvable",
}


@pytest.mark.parametrize("fichier", ["etat-civil-xlsx.yaml", "etat-civil-sqlite.yaml", "etat-civil-sql.yaml",
                                     "etat-civil-pdf.yaml"])
def test_etat_civil_meme_reponse_quel_que_soit_le_format(fichier):
    registre = charger(fichier)
    for sujet, attendu in ATTENDU_ETAT_CIVIL.items():
        obtenu = majeur(registre, sujet)
        assert obtenu == attendu or (isinstance(attendu, str) and str(obtenu).startswith(attendu)), (sujet, obtenu)


def test_excel_vraie_date_et_entetes_francais():
    registre = charger("etat-civil-xlsx.yaml")
    assert registre.lignes[-1]["Date de naissance"] == "1998-07-02"       # cellule date d'Excel -> ISO
    assert majeur(registre, "BF-0002") is True


def test_json_imbrique_et_correspondances():
    registre = charger("nationalite-json.yaml")
    def nationalite(sujet):
        try:
            return registre.calculer("nationalite_burkinabe", sujet)["nationalite_burkinabe"]
        except adaptateur.Refus as motif:
            return f"refus : {motif}"
    assert nationalite("BF-0001") is True            # « Burkinabè »
    assert nationalite("BF-0002") is True            # « BF »
    assert nationalite("BF-0006") is True            # « burkinabe »
    assert nationalite("BF-0018") is False           # « Ivoirienne »
    assert nationalite("BF-0020") is True            # ["Ivoirienne", "Burkinabè"] : double nationalité
    assert nationalite("BF-0013").startswith("refus : donnée insuffisante")      # vide
    assert nationalite("BF-0014").startswith("refus : donnée insuffisante : valeur non reconnue")   # « XX »


def test_csv_windows_1252_point_virgule():
    registre = charger("casier-csv.yaml")
    assert "Peines complémentaires" in registre.lignes[0]                 # accents bien décodés
    assert registre.calculer("casier_judiciaire_vierge", "BF-0001") == {"casier_judiciaire_vierge": True}
    assert registre.calculer("interdiction_sortie_territoire", "BF-0005") == {"interdiction_sortie_territoire": False}
    assert registre.calculer("interdiction_sortie_territoire", "BF-0008") == {"interdiction_sortie_territoire": True}
    with pytest.raises(adaptateur.Refus, match="donnée insuffisante"):
        registre.calculer("casier_judiciaire_vierge", "BF-0015")          # case vide


def test_csv_virgule_utf8(tmp_path):
    (tmp_path / "casier.csv").write_text("NIP,Nb condamnations,Peines complémentaires\nBF-0001,0,aucune\n",
                                         encoding="utf-8")
    registre = charger("casier-csv.yaml", **{DONNEES.as_posix() + "/casier.csv": (tmp_path / "casier.csv").as_posix()})
    assert registre.calculer("casier_judiciaire_vierge", "BF-0001") == {"casier_judiciaire_vierge": True}


def test_pdf_scanne_refuse_au_demarrage():
    with pytest.raises(ValueError, match="PDF scanné"):
        charger("etat-civil-pdf.yaml", **{"etat_civil.pdf": "etat_civil_scanne.pdf"})


def test_empreinte_de_la_source():
    import hashlib
    registre = charger("etat-civil-xlsx.yaml")
    assert registre.empreinte_source == hashlib.sha256((DONNEES / "etat_civil.xlsx").read_bytes()).hexdigest()


# --- API HTTP du jury : interrogée à chaque demande, authentification par secret, délai maximal ---

FICHES_API = {"BF-0001": [{"nip": "BF-0001", "naissance": {"date": "14/03/2001"}, "deces": {"date": ""}}],
              "BF-0003": [{"nip": "BF-0003", "naissance": {"date": "21/05/2010"}, "deces": {"date": ""}}]}


class FausseApi(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.headers.get("Authorization") != "Bearer jeton-jury-de-test":
            self.send_response(401); self.end_headers(); return
        nip = parse_qs(urlparse(self.path).query).get("nip", [""])[0]
        if nip == "BF-LENT":
            time.sleep(2)
        if nip not in FICHES_API:
            self.send_response(404); self.end_headers(); return
        corps = json.dumps({"resultats": FICHES_API[nip]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers()
        self.wfile.write(corps)

    def log_message(self, *_):
        pass


@pytest.fixture(scope="module")
def api():
    serveur = ThreadingHTTPServer(("127.0.0.1", 0), FausseApi)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    (TMP / "secrets/api_jury").write_text("jeton-jury-de-test")
    yield serveur.server_address[1]
    serveur.shutdown()


def test_api_du_jury(api):
    registre = charger("etat-civil-api.yaml", **{"{port}": str(api)})
    assert registre.lignes is None                          # rien n'est chargé : interrogée à chaque demande
    assert majeur(registre, "BF-0001") is True
    assert majeur(registre, "BF-0003") is False
    assert majeur(registre, "BF-0099") == "refus : introuvable"       # 404


def test_api_lente_ou_mauvais_secret_indisponible(api):
    registre = charger("etat-civil-api.yaml", **{"{port}": str(api)})
    with pytest.raises(adaptateur.SourceIndisponible):
        registre.calculer("age_entre", "BF-LENT", MAJEUR)                  # 2 s > délai de 1 s
    (TMP / "secrets/api_jury").write_text("mauvais-jeton")
    try:
        with pytest.raises(adaptateur.SourceIndisponible, match="HTTP 401"):
            registre.calculer("age_entre", "BF-0001", MAJEUR)
    finally:
        (TMP / "secrets/api_jury").write_text("jeton-jury-de-test")
