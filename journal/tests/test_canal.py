"""Canal de l'usager (ussd | web) : déduit du secret présenté, écrit au journal, visible dans l'historique.
Ajout de la colonne « canal » à un journal existant : les anciennes empreintes (et les reçus) restent valables."""
import importlib.util
import sqlite3
import threading

import respx

from conftest import CANAL, CHEMIN_JOURNAL, RACINE, URL_NATIONALITE, demande, mediateur
from test_mediateur import registre_qui_signe

WEB = {"X-Cle-Canal": "secret-de-test-canal-web"}

spec = importlib.util.spec_from_file_location("verifier_canal", RACINE / "journal/verifier.py")
verifier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verifier)


def ligne_du_journal(empreinte: str) -> dict:
    base = sqlite3.connect(CHEMIN_JOURNAL)
    base.row_factory = sqlite3.Row
    return dict(base.execute("SELECT * FROM journal WHERE hash = ?", (empreinte,)).fetchone())


def demande_bourse(client, sujet: str) -> str:
    client.agent["nom"] = "awa.ouedraogo"
    d = demande(demarche="bourse-nationale", sujet=sujet)
    assert client.post("/demandes", json=d).json()["statut"] == "en_attente"
    return d["id_demande"]


@respx.mock
def test_confirmation_par_le_web_ecrite_avec_canal_web_et_visible_partout(client):
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    id_demande = demande_bourse(client, "BF-0017")
    r = client.post(f"/demandes/{id_demande}/confirmer", json={"sujet_ref": "BF-0017"}, headers=WEB).json()
    assert ligne_du_journal(r["empreinte"])["canal"] == "web"
    # Le même historique est servi à l'USSD : la confirmation faite sur le web y figure, avec son canal
    historique = client.get("/usagers/BF-0017/historique", headers=CANAL).json()
    confirmation = next(l for l in historique if l["evenement"] == "confirmation")
    assert confirmation["canal"] == "web" and confirmation["empreinte"] == r["empreinte"]
    # Les lignes écrites pour l'agent n'ont pas de canal
    assert next(l for l in historique if l["evenement"] == "demande")["canal"] == ""


@respx.mock
def test_refus_et_retrait_par_ussd_ecrits_avec_canal_ussd(client):
    respx.post(URL_NATIONALITE).mock(side_effect=registre_qui_signe())
    id_demande = demande_bourse(client, "BF-0019")
    client.post(f"/demandes/{id_demande}/refuser", json={"sujet_ref": "BF-0019"}, headers=CANAL)
    id_retrait = demande_bourse(client, "BF-0019")
    client.post(f"/demandes/{id_retrait}/confirmer", json={"sujet_ref": "BF-0019"}, headers=WEB)
    r = client.post(f"/demandes/{id_retrait}/retirer", json={"sujet_ref": "BF-0019"}, headers=CANAL).json()
    assert ligne_du_journal(r["empreinte"])["canal"] == "ussd"
    historique = client.get("/usagers/BF-0019/historique", headers=WEB).json()
    assert next(l for l in historique if l["evenement"] == "refus-usager")["canal"] == "ussd"


def test_secret_vide_ou_absent_n_ouvre_aucun_canal(client, monkeypatch):
    monkeypatch.setitem(mediateur.SECRETS_CANAUX, "web", b"")
    assert client.get("/usagers/BF-0001/en-attente", headers={"X-Cle-Canal": ""}).status_code == 401
    assert client.get("/usagers/BF-0001/en-attente").status_code == 401
    assert client.get("/usagers/BF-0001/en-attente", headers=WEB).status_code == 401      # canal web fermé
    assert client.get("/usagers/BF-0001/en-attente", headers=CANAL).status_code == 200    # l'USSD continue


def test_ajout_de_la_colonne_canal_garde_les_anciennes_empreintes(tmp_path):
    """Journal écrit AVANT l'ajout du canal : même calcul qu'avant pour ses lignes, nouvelles lignes chaînées."""
    from tracabilite.journal import CHAMPS, ZEROS, Journal, empreinte
    chemin = tmp_path / "ancien.sqlite3"
    ancien = sqlite3.connect(chemin, isolation_level=None)
    anciens_champs = [c for c in CHAMPS if c != "canal"]
    ancien.execute(f"CREATE TABLE journal (n INTEGER PRIMARY KEY, ts TEXT, {', '.join(anciens_champs)}, "
                   "prev_hash TEXT, hash TEXT)")
    precedente = ZEROS
    for n in (1, 2):
        ligne = {"n": n, "ts": "2026-11-16T10:00:00Z", **{c: "x" for c in anciens_champs}, "prev_hash": precedente}
        ligne["hash"] = empreinte(ligne)           # aucune clé « canal » : calcul d'avant le 17/11
        ancien.execute(f"INSERT INTO journal ({', '.join(ligne)}) VALUES ({', '.join('?' * len(ligne))})",
                       list(ligne.values()))
        precedente = ligne["hash"]
    ancien.close()

    base = sqlite3.connect(chemin, check_same_thread=False, isolation_level=None)
    base.row_factory = sqlite3.Row
    journal = Journal(base, threading.RLock())          # ajoute la colonne (NULL pour les anciennes lignes)
    journal.ecrire(evenement="confirmation", resultat="ok", canal="web")
    integre, message, lignes = verifier.verifier(str(chemin))
    assert integre and message == "Journal intègre : 3 lignes"
    assert [l["canal"] for l in lignes] == [None, None, "web"]
    assert lignes[1]["hash"] == precedente               # empreinte (donc reçu) inchangée

    # Mettre un canal sur une ancienne ligne se voit
    base.execute("DROP TRIGGER journal_sans_modification")
    base.execute("UPDATE journal SET canal = 'web' WHERE n = 1")
    assert verifier.verifier(str(chemin))[1] == "Ligne 1 modifiée"


@respx.mock
def test_historique_donne_les_seuils_de_la_demarche(client):
    from conftest import URL_REGISTRE
    respx.post(URL_REGISTRE).mock(side_effect=registre_qui_signe())
    client.agent["nom"] = "issa.sawadogo"
    client.post("/demandes", json=demande(sujet="BF-0010"))
    ligne = client.get("/usagers/BF-0010/historique", headers=CANAL).json()[0]
    assert ligne["attributs"][0]["code"] == "age_entre" and ligne["attributs"][0]["parametres"]["min"] == 18
