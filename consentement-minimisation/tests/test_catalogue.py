"""Catalogue actif : les trois démarches du cadre (concours direct, CEFORE, certificat de nationalité), leur validation
au chargement, et le refus d'une version invalide (l'ancienne reste en vigueur, la passerelle continue de tourner)."""
import pytest
from conftest import RACINE

from app import main as mediateur
from consentement import catalogue


def charger_le_catalogue():
    return catalogue.charger()          # lève CatalogueInvalide si le catalogue du dépôt est invalide


def test_catalogue_actif_trois_demarches_du_cadre():
    chat = charger_le_catalogue()
    assert set(chat["demarches"]) == {"concours-direct", "entreprise-individuelle-cefore", "certificat-nationalite"}
    attributs = {code: [a["attribut"] for a in d["attributs"]] for code, d in chat["demarches"].items()}
    assert attributs == {"concours-direct": ["majeur", "nationalite_bf", "casier_vierge"],
                         "entreprise-individuelle-cefore": ["identite", "casier_vierge"],
                         "certificat-nationalite": ["naissance_filiation"]}
    services = {code: d["services"] for code, d in chat["demarches"].items()}
    assert services == {"concours-direct": ["direction-concours"], "entreprise-individuelle-cefore": ["cefore"],
                        "certificat-nationalite": ["tribunal"]}
    assert set(chat["services"]) == {"direction-concours", "cefore", "tribunal"}


def test_duree_de_l_accord_pour_chaque_demarche_a_consentement():
    chat = charger_le_catalogue()
    for code, d in chat["demarches"].items():
        assert d["base"] in ("base_legale", "consentement"), code
        if d["base"] == "consentement":
            assert type(d["duree_accord_heures"]) is int and d["duree_accord_heures"] > 0, code


def test_demarches_retirees_pas_dans_le_catalogue_actif_mais_conservees():
    chat = charger_le_catalogue()
    inactives = (RACINE / "consentement-minimisation/catalogue/demarches-inactives.yaml").read_text(encoding="utf-8")
    for code in ("passeport-ordinaire", "bourse-nationale", "verifier-majorite"):
        assert code not in chat["demarches"] and f"  {code}:" in inactives


def test_consentement_sans_duree_refuse(monkeypatch, tmp_path):
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8")
    assert "    duree_accord_heures: 168" in texte
    with pytest.raises(catalogue.CatalogueInvalide, match="duree_accord_heures"):
        catalogue.charger(texte.replace("    duree_accord_heures: 168          # 7 jours : le temps de constituer le dossier\n", "").encode())


def test_apercus_tiennent_dans_un_ecran_ussd(monkeypatch):
    """L'aperçu est fabriqué depuis le catalogue : jamais en dur, et chaque aperçu tient dans 160 caractères."""
    chat = charger_le_catalogue()
    monkeypatch.setattr(mediateur, "CAT", chat)
    exemples = {
        "concours-direct": ("direction-concours", [("majeur", 1), ("nationalite_bf", 1), ("casier_vierge", 1)]),
        "entreprise-individuelle-cefore": ("cefore", [("identite", '{"nom": "KABORE", "prenoms": "Aminata"}'),
                                                      ("casier_vierge", 1)]),
        "certificat-nationalite": ("tribunal", [("naissance_filiation", '{"date_naissance": "2001-03-14", '
                                                 '"lieu_naissance": "Ouagadougou", "pere": "Issaka KABORE", '
                                                 '"mere": "Salimata KABORE"}')]),
    }
    for demarche, (service, volets) in exemples.items():
        d = {"id_demande": "test", "demandeur": service, "demarche": demarche,
             "finalite": chat["demarches"][demarche]["finalite"], "expire_le": 0,
             "volets": [{"attribut": a, "valeur": v, "statut": "ok"} for a, v in volets]}
        apercu = mediateur.apercu(d)["apercu"]
        assert "Rien d'autre." in apercu
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
    assert "agrement-commercial" in chat["demarches"]
    # Erreur volontaire (démo « le médiateur refuse de démarrer ») : finalité supprimée
    (dossier / "demarches.yaml").write_text(texte.replace("    finalite: instruction d'une demande d'agrément d'activité commerciale\n", ""),
                                            encoding="utf-8")
    import pytest
    with pytest.raises(catalogue.CatalogueInvalide, match="agrement-commercial.*finalité manquante"):
        catalogue.charger()


# --- Catalogue en direct : une version invalide est REFUSÉE, l'ancienne reste en vigueur, jamais d'arrêt ---

DATE_DE_NAISSANCE = """
  curiosite-date-naissance:
    libelle: Date de naissance complète
    services: [direction-concours]
    finalite: curiosité
    base: consentement
    duree_accord_heures: 24
    attributs:
      - {attribut: date_naissance, libelle: date de naissance}
"""

SEUIL_NON_DECLARE = """
  majorite-a-21-ans:
    libelle: Majorité à 21 ans
    services: [direction-concours]
    finalite: vérification de l'âge
    base: consentement
    duree_accord_heures: 24
    attributs:
      - {attribut: majeur, parametres: {min: 21, date_reference: aujourd'hui}, libelle: 21 ans}
"""

DOUBLE_CLE = """
  nationalite-cefore:
    libelle: Nationalité pour le CEFORE
    services: [cefore]
    finalite: vérification de la nationalité
    base: consentement
    duree_accord_heures: 24
    attributs:
      - {attribut: nationalite_bf, libelle: burkinabè}
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
    (DOUBLE_CLE, "n'autorise pas cefore à demander « nationalite_bf »"),
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
    services: [direction-concours]
    finalite: vérification de la majorité civile
    base: base_legale
    texte: Code des personnes et de la famille, loi n°012-2025/ALT (majorité civile à 18 ans accomplis)
    attributs:
      - {attribut: majeur, parametres: {min: 18, date_reference: aujourd'hui}, libelle: majeur}
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


def test_cefore_en_base_legale_refuse_au_chargement(monkeypatch, tmp_path):
    """Passer le CEFORE en base légale dans le catalogue : refusé au chargement (l'état civil et le casier n'ont
    déclaré que le consentement pour le CEFORE). Le registre refuse aussi : test_registre.py."""
    texte = (RACINE / "consentement-minimisation/catalogue/demarches.yaml").read_text(encoding="utf-8")
    avant = """    base: consentement
    duree_accord_heures: 168          # 7 jours : le temps de constituer le dossier
"""
    assert avant in texte
    texte = texte.replace(avant, """    base: base_legale
    texte: Décret relatif à l'immatriculation (texte inventé pour le test)
""")
    with pytest.raises(catalogue.CatalogueInvalide) as refus:
        catalogue.charger(texte.encode("utf-8"))
    for registre in ("etat-civil", "casier"):
        assert (f"démarche « entreprise-individuelle-cefore » : le registre {registre} n'accepte pas la base "
                f"« base_legale » pour cefore") in str(refus.value)
