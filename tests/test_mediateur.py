"""Médiateur : signature, délai, rejeu, finalité, consentement, journal."""
import importlib.util
import json
import sqlite3

import httpx
import respx
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from conftest import CANAL, CHEMIN_JOURNAL, RACINE, URL_REGISTRE, demande, jeton_registre


def registre_qui_signe(**modifs):
    """Faux registre : signe une réponse pour la demande reçue."""
    def repondre(requete):
        return httpx.Response(200, json={"jeton": jeton_registre(json.loads(requete.content), **modifs)})
    return repondre


def journal_de(id_demande_ignore=None):
    base = sqlite3.connect(CHEMIN_JOURNAL)
    base.row_factory = sqlite3.Row
    return [dict(l) for l in base.execute("SELECT * FROM journal ORDER BY n")]


@respx.mock
def test_signature_valide_acceptee(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "remise" and r["jeton"]
    evenements = [l["evenement"] for l in journal_de()[-3:]]
    assert evenements == ["demande", "reponse-registre", "remise"]


@respx.mock
def test_signature_fausse_refusee(client):
    autre_cle = Ed25519PrivateKey.generate()
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe(cle=autre_cle))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "refuse" and "signature invalide" in r["motif"] and "jeton" not in r
    assert journal_de()[-1]["evenement"] == "alerte"


@respx.mock
def test_claims_modifies_refuses(client):
    # Le registre (ou quelqu'un sur le chemin) ajoute la date de naissance : refusé
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe(date_naissance="2001-03-14"))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "refuse" and "contenu inattendu" in r["motif"]


@respx.mock
def test_delai_depasse_refuse(client):
    respx.post(URL_REGISTRE).mock(side_effect=httpx.ReadTimeout("trop lent"))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "indisponible" and "rien n'a été deviné" in r["motif"]
    assert journal_de()[-1]["resultat"] == "indisponible"


@respx.mock
def test_registre_coupe_refuse(client):
    respx.post(URL_REGISTRE).mock(side_effect=httpx.ConnectError("injoignable"))
    r = client.post("/demandes", json=demande()).json()
    assert r["statut"] == "indisponible" and "injoignable" in r["motif"]


@respx.mock
def test_refus_du_registre_transmis(client):
    respx.post(URL_REGISTRE).mock(return_value=httpx.Response(200, json={"refus": "personne décédée"}))
    r = client.post("/demandes", json=demande(sujet="BF-0007")).json()
    assert r["statut"] == "refuse" and "personne décédée" in r["motif"]


@respx.mock
def test_rejeu_une_seule_execution(client):
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande()
    premiere = client.post("/demandes", json=d).json()
    seconde = client.post("/demandes", json=d).json()
    assert route.call_count == 1
    assert premiere["statut"] == seconde["statut"] == "remise"
    assert "jeton" not in seconde        # déjà remis : le médiateur l'a effacé


@respx.mock
def test_meme_id_pour_une_autre_demande_refuse(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande()
    client.post("/demandes", json=d)
    r = client.post("/demandes", json={**d, "sujet_ref": "BF-0002"})
    assert r.status_code == 409


@respx.mock
def test_mauvaise_finalite_refusee(client):
    route = respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    r = client.post("/demandes", json=demande(finalite="curiosité")).json()
    assert r["statut"] == "refuse" and r["motif"] == "finalité non autorisée"
    assert route.call_count == 0


@respx.mock
def test_demarche_d_un_autre_service_refusee(client):
    # Issa (concours) tente la démarche « bourse » : refusé, le service vient du jeton
    r = client.post("/demandes", json=demande(demarche="bourse")).json()
    assert r["statut"] == "refuse" and "non autorisée pour ce service" in r["motif"]


@respx.mock
def test_consentement_apercu_puis_confirmation(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse", sujet="BF-0012")
    assert client.post("/demandes", json=d).json()["statut"] == "en_attente"
    assert client.get(f"/demandes/{d['id_demande']}").json()["statut"] == "en_attente"

    attente = client.get("/usagers/BF-0012/en-attente", headers=CANAL).json()
    assert attente[0]["apercu"] == "Le service des bourses recevra : majeur = oui. Rien d'autre."
    confirmation = client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": "BF-0012"}, headers=CANAL)
    assert confirmation.json()["statut"] == "confirmee" and len(confirmation.json()["empreinte"]) == 64

    remise = client.get(f"/demandes/{d['id_demande']}").json()
    assert remise["statut"] == "remise" and remise["jeton"]
    assert "jeton" not in client.get(f"/demandes/{d['id_demande']}").json()   # remis une seule fois


@respx.mock
def test_refus_par_l_usager(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse", sujet="BF-0013")
    client.post("/demandes", json=d)
    client.post(f"/demandes/{d['id_demande']}/refuser", json={"sujet_ref": "BF-0013"}, headers=CANAL)
    r = client.get(f"/demandes/{d['id_demande']}").json()
    assert r["statut"] == "refuse" and "jeton" not in r


@respx.mock
def test_un_autre_usager_ne_peut_pas_confirmer(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse", sujet="BF-0014")
    client.post("/demandes", json=d)
    r = client.post(f"/demandes/{d['id_demande']}/confirmer", json={"sujet_ref": "BF-0015"}, headers=CANAL)
    assert r.status_code == 404


@respx.mock
def test_consentement_expire(client):
    client.agent["nom"] = "awa.ouedraogo"
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    d = demande(demarche="bourse", sujet="BF-0016")
    client.post("/demandes", json=d)
    sqlite3.connect(CHEMIN_JOURNAL, isolation_level=None).execute(
        "UPDATE demandes SET expire_le = 0 WHERE id_demande = ?", (d["id_demande"],))
    r = client.get(f"/demandes/{d['id_demande']}").json()
    assert r["statut"] == "expiree" and "jeton" not in r


def test_canal_usager_sans_secret_refuse(client):
    assert client.get("/usagers/BF-0001/en-attente").status_code == 401


@respx.mock
def test_historique_sans_la_valeur(client):
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    client.post("/demandes", json=demande(sujet="BF-0018"))
    historique = client.get("/usagers/BF-0018/historique", headers=CANAL).json()
    assert [l["evenement"] for l in historique] == ["remise", "reponse-registre", "demande"]
    assert historique[0]["service"] == "La direction des concours de la fonction publique"
    assert "texte fictif" in historique[0]["texte_base"]
    texte = json.dumps(historique, ensure_ascii=False)
    assert "true" not in texte and "= oui" not in texte and "BF-0018" not in texte


def test_journal_integre_puis_ligne_modifiee_detectee():
    spec = importlib.util.spec_from_file_location("verifier", RACINE / "journal/verifier.py")
    verifier = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(verifier)
    from app.journal import empreinte
    lignes = journal_de()
    assert all(verifier.empreinte(l) == empreinte(l) == l["hash"] for l in lignes)   # même calcul
    integre, message, _ = verifier.verifier(str(CHEMIN_JOURNAL))
    assert integre, message

    # Un administrateur modifie directement la ligne 2 dans le fichier SQLite
    base = sqlite3.connect(CHEMIN_JOURNAL, isolation_level=None)
    base.execute("DROP TRIGGER journal_sans_modification")
    base.execute("UPDATE journal SET demandeur = 'quelqu-un-d-autre' WHERE n = 2")
    integre, message, _ = verifier.verifier(str(CHEMIN_JOURNAL))
    assert not integre and message == "Ligne 2 modifiée"
