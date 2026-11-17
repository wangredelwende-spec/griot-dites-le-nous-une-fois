"""Repli « casier vierge » du passeport : UNE ligne du catalogue change, aucun code (JOUR_J_DONNEES_JURY.md).

Le casier du jury risque de n'avoir pas de colonne « peines complémentaires » : la démarche passeport doit
pouvoir basculer sur « casier judiciaire vierge » en remplaçant une seule ligne de consentement-minimisation/catalogue/demarches.yaml.
Le catalogue doit rester VALIDE (sinon le médiateur refuse de démarrer) et sans avertissement de double clé
(sinon le registre casier refuserait de répondre au service passeport). L'aperçu USSD suit tout seul :
il est fabriqué depuis le catalogue, jamais en dur.
"""
import pytest
from conftest import RACINE

from app import main as mediateur
from consentement import catalogue

LIGNE_INTERDICTION = ("- {attribut: interdiction_sortie_territoire, "
                      "libelle: interdiction de sortie du territoire, attendu: false}")
LIGNE_REPLI = ("- {attribut: casier_judiciaire_vierge, libelle: casier judiciaire vierge, "
               "si_non: \"casier non vierge : dossier à instruire\"}")


def charger_le_catalogue(monkeypatch, tmp_path, repli):
    """Charge le catalogue du dépôt, ou sa copie avec la SEULE ligne du casier passeport remplacée."""
    dossier = tmp_path / "catalogue"
    dossier.mkdir(exist_ok=True)
    (dossier / "annuaire.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_bytes())
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8")
    assert LIGNE_INTERDICTION in texte, "la ligne à remplacer en repli a disparu du catalogue"
    if repli:
        texte = texte.replace(LIGNE_INTERDICTION, LIGNE_REPLI)
    (dossier / "demarches.yaml").write_text(texte, encoding="utf-8")
    monkeypatch.setattr(catalogue, "CATALOGUE", dossier)
    return catalogue.charger()          # lève CatalogueInvalide si le repli est mal formé


def attributs_du_passeport(chat):
    return [a["attribut"] for a in chat["demarches"]["passeport-ordinaire"]["attributs"]]


def test_reglage_normal(monkeypatch, tmp_path):
    chat = charger_le_catalogue(monkeypatch, tmp_path, repli=False)
    # Pas d'âge : l'ONI le connaît déjà par l'enrôlement de la CNIB (option A du 16/11)
    assert attributs_du_passeport(chat) == ["nationalite_burkinabe", "interdiction_sortie_territoire"]
    # charger() refuse désormais toute démarche que la double clé d'un registre interdirait : réussir suffit


def test_reglage_repli_une_ligne(monkeypatch, tmp_path):
    chat = charger_le_catalogue(monkeypatch, tmp_path, repli=True)
    assert attributs_du_passeport(chat)[-1] == "casier_judiciaire_vierge"
    # Double clé : le registre casier autorise le service passeport sur « vierge », sinon il refuserait
    # charger() refuse désormais toute démarche que la double clé d'un registre interdirait : réussir suffit


def test_apercu_uissd_suit_tout_seul(monkeypatch, tmp_path):
    """L'aperçu est fabriqué depuis le catalogue : il change avec la ligne, sans autre modification."""
    for repli, volets, attendu in (
        (False, [("nationalite_burkinabe", True),
                 ("interdiction_sortie_territoire", False)], "interdiction de sortie du territoire = non"),
        (True, [("nationalite_burkinabe", True),
                ("casier_judiciaire_vierge", True)], "casier judiciaire vierge = oui"),
    ):
        chat = charger_le_catalogue(monkeypatch, tmp_path, repli=repli)
        monkeypatch.setattr(mediateur, "CAT", chat)
        d = {"id_demande": "test", "demandeur": "service-passeport", "demarche": "passeport-ordinaire",
             "finalite": "établissement d'un passeport ordinaire", "expire_le": 0,
             "volets": [{"attribut": a, "valeur": v, "statut": "ok"} for a, v in volets]}
        apercu = mediateur.apercu(d)["apercu"]
        assert attendu in apercu
        assert len(apercu) <= 160, f"écran USSD trop long ({len(apercu)}) : {apercu}"


def test_demarche_a_coller_en_direct(monkeypatch, tmp_path):
    """La démarche de docs/demarche_a_coller.yaml, collée à la fin du catalogue, est valide et sans avertissement
    de double clé (les registres l'autorisent déjà) : la démo « ajouter une démarche » ne peut pas échouer."""
    dossier = tmp_path / "catalogue"
    dossier.mkdir()
    (dossier / "annuaire.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_bytes())
    a_coller = "\n".join(l for l in (RACINE / "docs/demarche_a_coller.yaml").read_text(encoding="utf-8").splitlines()
                         if not l.startswith("#"))
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8").rstrip("\n") + "\n" + a_coller + "\n"
    (dossier / "demarches.yaml").write_text(texte, encoding="utf-8")
    monkeypatch.setattr(catalogue, "CATALOGUE", dossier)
    chat = catalogue.charger()
    assert "aide-transport-etudiant" in chat["demarches"]
    # Erreur volontaire (démo « le médiateur refuse de démarrer ») : finalité supprimée
    (dossier / "demarches.yaml").write_text(texte.replace("    finalite: attribution de l'aide au transport des étudiants\n", ""),
                                            encoding="utf-8")
    import pytest
    with pytest.raises(catalogue.CatalogueInvalide, match="aide-transport-etudiant.*finalité manquante"):
        catalogue.charger()


# --- Catalogue en direct : une version invalide est REFUSÉE, l'ancienne reste en vigueur, jamais d'arrêt ---

DATE_DE_NAISSANCE = """
  curiosite-date-naissance:
    libelle: Date de naissance complète
    services: [mairie]
    finalite: curiosité
    base: consentement
    attributs:
      - {attribut: date_naissance, libelle: date de naissance}
"""

SEUIL_NON_DECLARE = """
  majorite-a-21-ans:
    libelle: Majorité à 21 ans
    services: [mairie]
    finalite: vérification de l'âge
    base: consentement
    attributs:
      - {attribut: age_entre, parametres: {min: 21, date_reference: aujourd'hui}, libelle: 21 ans}
"""

DOUBLE_CLE = """
  nationalite-mairie:
    libelle: Nationalité pour la mairie
    services: [mairie]
    finalite: vérification de la nationalité
    base: consentement
    attributs:
      - {attribut: nationalite_burkinabe, libelle: burkinabè}
"""


def lignes_catalogue():
    with mediateur.VERROU:
        return [dict(l) for l in mediateur.base.execute(
            "SELECT resultat, motif FROM journal WHERE evenement = 'catalogue' ORDER BY n")]


def ecrire_et_surveiller(dossier, texte):
    import os, time
    fichier = dossier / "demarches.yaml"
    fichier.write_text(texte, encoding="utf-8")
    t = time.time() + len(lignes_catalogue())          # date de modification toujours nouvelle
    os.utime(fichier, (t, t))
    mediateur._VU["verification"] = 0                  # pas d'attente d'une seconde dans les tests
    mediateur.surveiller_catalogue()


@pytest.mark.parametrize("ajout, raison", [
    (DATE_DE_NAISSANCE, "attribut inconnu « date_naissance » (aucun registre ne le déclare)"),
    (SEUIL_NON_DECLARE, "seuil ou date non déclaré"),
    (DOUBLE_CLE, "n'autorise pas mairie à demander « nationalite_burkinabe »"),
    ("\n  cassee: [ : :\n", "YAML cassé"),
])
def test_catalogue_invalide_refuse_ancien_garde(monkeypatch, tmp_path, ajout, raison, client):
    dossier = tmp_path / "catalogue"
    dossier.mkdir()
    (dossier / "annuaire.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_bytes())
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8")
    monkeypatch.setattr(catalogue, "CATALOGUE", dossier)
    monkeypatch.setattr(mediateur, "CAT", mediateur.CAT)
    monkeypatch.setattr(mediateur, "REFUS_CATALOGUE", {})
    ancien = mediateur.CAT["empreinte"]
    avant = len(lignes_catalogue())

    ecrire_et_surveiller(dossier, texte.rstrip("\n") + "\n" + ajout)
    assert mediateur.CAT["empreinte"] == ancien                     # l'ancien catalogue reste en vigueur
    assert raison in mediateur.REFUS_CATALOGUE["raison"]
    public = client.get("/catalogue").json()                       # ce que voit le guichet
    assert public["empreinte"] == ancien and raison in public["refus"]["raison"]
    assert "curiosite-date-naissance" not in public["demarches"]
    nouvelles = lignes_catalogue()[avant:]
    assert nouvelles[-1]["resultat"] == "refuse" and raison in nouvelles[-1]["motif"]
    # Le médiateur répond toujours
    assert client.get("/sante").status_code == 200

    # Une version corrigée et valide remplace l'ancienne ; sa nouvelle empreinte entre au journal
    ecrire_et_surveiller(dossier, texte.rstrip("\n") + "\n" + DEMARCHE_VALIDE)
    assert mediateur.REFUS_CATALOGUE == {} and "test-valide" in mediateur.CAT["demarches"]
    assert mediateur.CAT["empreinte"] != ancien
    assert lignes_catalogue()[-1] == {"resultat": "ok", "motif": f"catalogue rechargé : "
                                      f"{len(mediateur.CAT['demarches'])} démarches, sha256 {mediateur.CAT['empreinte']}"}


DEMARCHE_VALIDE = """
  test-valide:
    libelle: Vérifier la majorité (test)
    services: [service-bourses]
    finalite: vérification de la majorité civile
    base: consentement
    attributs:
      - {attribut: age_entre, parametres: {min: 18, date_reference: aujourd'hui}, libelle: majeur}
"""


def test_demarche_refusee_de_la_demo(monkeypatch, tmp_path):
    """docs/demarche_refusee.yaml (essai raté de test-manuel.md, scène 4) est bien REFUSÉE : date de naissance."""
    dossier = tmp_path / "catalogue"
    dossier.mkdir()
    (dossier / "annuaire.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_bytes())
    a_coller = "\n".join(l for l in (RACINE / "docs/demarche_refusee.yaml").read_text(encoding="utf-8").splitlines()
                         if not l.startswith("#"))
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8").rstrip("\n") + "\n" + a_coller + "\n"
    monkeypatch.setattr(catalogue, "CATALOGUE", dossier)
    with pytest.raises(catalogue.CatalogueInvalide, match="attribut inconnu « date_naissance »"):
        catalogue.charger(texte.encode("utf-8"))


def test_passeport_en_base_legale_refuse_au_chargement(monkeypatch, tmp_path):
    """Passer le passeport en base légale dans le catalogue : refusé au chargement (la nationalité et le casier
    n'ont déclaré que le consentement pour le service passeport). Le registre refuse aussi : test_registre.py."""
    dossier = tmp_path / "catalogue"
    dossier.mkdir()
    (dossier / "annuaire.yaml").write_bytes((RACINE / "consentement-minimisation/catalogue/annuaire.yaml").read_bytes())
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8")
    avant = """    finalite: établissement d'un passeport ordinaire
    base: consentement
"""
    assert avant in texte
    texte = texte.replace(avant, """    finalite: établissement d'un passeport ordinaire
    base: base_legale
    texte: Décret relatif au passeport ordinaire
""")
    monkeypatch.setattr(catalogue, "CATALOGUE", dossier)
    with pytest.raises(catalogue.CatalogueInvalide) as refus:
        catalogue.charger(texte.encode("utf-8"))
    for registre in ("nationalite", "casier"):
        assert (f"démarche « passeport-ordinaire » : le registre {registre} n'accepte pas la base « base_legale » "
                f"pour service-passeport") in str(refus.value)
