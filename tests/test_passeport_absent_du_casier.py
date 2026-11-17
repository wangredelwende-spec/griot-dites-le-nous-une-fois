"""Passeport : une personne ABSENTE du casier n'obtient JAMAIS « casier vierge » (ni « pas d'interdiction de
sortie ») sans confirmation d'identité. Elle reçoit un refus.

Quatre combinaisons, toutes couvertes :
- réglage du catalogue : interdiction de sortie du territoire (normal) | casier judiciaire vierge (repli jour J) ;
- réglage du casier (registres/adaptateurs/casier.yaml) : absence: refus (dépôt) | absence: vierge (à trancher jour J).
Avec « absence: refus », c'est le REGISTRE du casier qui refuse (introuvable). Avec « absence: vierge », le médiateur
demande d'abord « personne_connue » à l'état civil, qui REFUSE ce service au passeport (double clé) : refus.
BF-0003 n'a aucune ligne dans le casier fictif. Un identifiant inventé (BF-0099) est traité pareil.
"""
import json

import httpx
import pytest
import respx
from conftest import (ADAPTATEUR_TEST, RACINE, URL_CASIER, URL_NATIONALITE, URL_REGISTRE, demande, jeton_registre,
                      refus_registre)

from app import main as mediateur
from registre_app import adaptateur

INTERDICTION = {"attribut": "interdiction_sortie_territoire", "libelle": "interdiction de sortie du territoire",
                "attendu": False, "parametres": {}}
VIERGE = {"attribut": "casier_judiciaire_vierge", "libelle": "casier judiciaire vierge", "parametres": {}}
ABSENTS = ("BF-0003", "BF-0099")


def casier(absence: str, tmp_path):
    texte = (RACINE / "registres/adaptateurs/casier.yaml").read_text(encoding="utf-8")
    chemin = tmp_path / "casier.yaml"
    chemin.write_text(texte.replace("absence: refus", f"absence: {absence}").replace(
        "/donnees/casier.csv", (RACINE / "registres/donnees_fictives/casier.csv").as_posix()), encoding="utf-8")
    return adaptateur.Adaptateur(chemin)


# --- absence: refus (réglage du dépôt) : le registre du casier refuse lui-même ---

@pytest.mark.parametrize("attribut", [INTERDICTION["attribut"], VIERGE["attribut"]])
@pytest.mark.parametrize("sujet", ABSENTS)
def test_absence_refus_le_casier_refuse(tmp_path, attribut, sujet):
    registre = casier("refus", tmp_path)
    assert registre.autorise(attribut, "service-passeport")       # les deux réglages sont permis au passeport
    with pytest.raises(adaptateur.Refus, match="introuvable"):
        registre.calculer(attribut, sujet)


# --- absence: vierge : l'identité doit être confirmée par l'état civil, qui ne la confirme pas au passeport ---

def test_l_etat_civil_ne_confirme_pas_l_identite_au_passeport():
    etat_civil = adaptateur.Adaptateur(ADAPTATEUR_TEST)
    assert not etat_civil.autorise("personne_connue", "service-passeport")
    assert not etat_civil.autorise("age_entre", "service-passeport")


@pytest.mark.parametrize("reglage", [INTERDICTION, VIERGE], ids=["interdiction", "vierge"])
@pytest.mark.parametrize("sujet", ABSENTS)
@respx.mock
def test_absence_vierge_passeport_refuse(client, monkeypatch, tmp_path, reglage, sujet):
    reel = casier("vierge", tmp_path)
    passeport = mediateur.CAT["demarches"]["passeport-ordinaire"] | {
        "attributs": [{"attribut": "nationalite_burkinabe", "libelle": "burkinabè", "parametres": {}}, reglage]}
    monkeypatch.setattr(mediateur, "CAT", mediateur.CAT | {
        "absence_vierge": {"casier"},
        "demarches": mediateur.CAT["demarches"] | {"passeport-ordinaire": passeport}})

    def etat_civil(requete):
        corps = json.loads(requete.content)
        # Comme le vrai registre : double clé -> refus signé pour le service passeport
        assert corps["attribut"] == "personne_connue" and corps["destinataire"] == "service-passeport"
        return httpx.Response(200, json={"jeton": refus_registre(corps, motif="service non autorisé")})

    def registre_casier(requete):          # le casier « absence: vierge » répondrait favorablement…
        corps = json.loads(requete.content)
        return httpx.Response(200, json={"jeton": jeton_registre(corps, **reel.calculer(corps["attribut"], sujet))})

    respx.post(URL_REGISTRE).mock(side_effect=etat_civil)
    appel_casier = respx.post(URL_CASIER).mock(side_effect=registre_casier)
    respx.post(URL_NATIONALITE).mock(side_effect=lambda r: httpx.Response(
        200, json={"jeton": jeton_registre(json.loads(r.content))}))
    client.agent["nom"] = "moussa.kone"
    r = client.post("/demandes", json=demande(demarche="passeport-ordinaire", sujet=sujet)).json()
    v = next(v for v in r["volets"] if v["attribut"] == reglage["attribut"])
    # …mais il n'est jamais appelé : identité non confirmée -> refus, aucune valeur, rien dans l'aperçu
    assert v["statut"] == "refuse" and v["motif"] == "identité non confirmée par l'état civil"
    assert v.get("valeur") is None and not v.get("jeton") and not appel_casier.called
    from conftest import CANAL
    attente = client.get(f"/usagers/{sujet}/en-attente", headers=CANAL).json()
    assert attente and "casier" not in attente[0]["apercu"] and "interdiction" not in attente[0]["apercu"]
