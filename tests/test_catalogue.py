"""Repli « casier vierge » du passeport : UNE ligne du catalogue change, aucun code (JOUR_J_DONNEES_JURY.md).

Le casier du jury risque de n'avoir pas de colonne « peines complémentaires » : la démarche passeport doit
pouvoir basculer sur « casier judiciaire vierge » en remplaçant une seule ligne de catalogue/demarches.yaml.
Le catalogue doit rester VALIDE (sinon le médiateur refuse de démarrer) et sans avertissement de double clé
(sinon le registre casier refuserait de répondre au service passeport). L'aperçu USSD suit tout seul :
il est fabriqué depuis le catalogue, jamais en dur.
"""
from conftest import RACINE

from app import catalogue, main as mediateur

LIGNE_INTERDICTION = ("- {attribut: interdiction_sortie_territoire, "
                      "libelle: interdiction de sortie du territoire, attendu: false}")
LIGNE_REPLI = ("- {attribut: casier_judiciaire_vierge, libelle: casier judiciaire vierge, "
               "si_non: \"casier non vierge : dossier à instruire\"}")


def charger_le_catalogue(monkeypatch, tmp_path, repli):
    """Charge le catalogue du dépôt, ou sa copie avec la SEULE ligne du casier passeport remplacée."""
    dossier = tmp_path / "catalogue"
    dossier.mkdir(exist_ok=True)
    (dossier / "annuaire.yaml").write_bytes((RACINE / "catalogue/annuaire.yaml").read_bytes())
    texte = (RACINE / "catalogue/demarches.yaml").read_text(encoding="utf-8")
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
    assert attributs_du_passeport(chat) == ["age_entre", "nationalite_burkinabe",
                                            "interdiction_sortie_territoire"]
    assert chat["avertissements"] == []


def test_reglage_repli_une_ligne(monkeypatch, tmp_path):
    chat = charger_le_catalogue(monkeypatch, tmp_path, repli=True)
    assert attributs_du_passeport(chat)[-1] == "casier_judiciaire_vierge"
    # Double clé : le registre casier autorise le service passeport sur « vierge », sinon il refuserait
    assert chat["avertissements"] == []


def test_apercu_uissd_suit_tout_seul(monkeypatch, tmp_path):
    """L'aperçu est fabriqué depuis le catalogue : il change avec la ligne, sans autre modification."""
    for repli, volets, attendu in (
        (False, [("age_entre", True), ("nationalite_burkinabe", True),
                 ("interdiction_sortie_territoire", False)], "interdiction de sortie du territoire = non"),
        (True, [("age_entre", True), ("nationalite_burkinabe", True),
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
