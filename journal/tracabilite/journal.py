"""Journal chaîné par hachage (SQLite), en ajout seul.

Chaque ligne contient l'empreinte de la précédente :
    hash = SHA-256(prev_hash + JSON canonique de la ligne sans « hash »)
Modifier une ligne casse la chaîne à cet endroit (journal/verifier.py l'indique).
Le journal consigne le FAIT, jamais le CONTENU : « le service des bourses a consulté l'attribut
majeur », jamais « majeur = oui ». Le citoyen y est pseudonymisé (HMAC de son identifiant).
« canal » dit d'où vient une action de l'usager (ussd | web ; vide pour une action d'agent). Colonne ajoutée
le 17/11 : les lignes écrites avant n'ont pas de canal (NULL), et une valeur NULL est exclue du calcul de
l'empreinte, donc leur empreinte (et les reçus déjà remis) ne change pas.
Même principe pour les trois colonnes du 17/11 (attributs_demandes, attributs_transmis, attributs_refuses) :
des NOMS d'attributs séparés par « + », jamais leurs valeurs. « id_demande » est l'identifiant de corrélation :
il relie toutes les lignes d'une même démarche (demande, réponses des registres, confirmation, remise).
« agent » : l'identifiant de l'agent (Keycloak) ou du compte technique (« api-<service> » pour une clé API).
« statut » (17/11) : autorisée | refusée | réussie | échouée | indisponible (statut_de), même règle d'empreinte.
"""
import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone

ZEROS = "0" * 64
# « id_demande » relie la ligne à la trace du registre (double trace, verifier.py --registres)
CHAMPS = ("id_demande", "agent", "demandeur", "demarche", "finalite", "base", "attribut", "registre", "sujet",
          "evenement", "resultat", "motif", "canal", "attributs_demandes", "attributs_transmis", "attributs_refuses",
          "statut")


def statut_de(evenement: str, resultat: str) -> str:
    """Statut lisible de la ligne : autorisée | refusée | réussie | échouée | indisponible.
    - « demande » : la passerelle autorise ou refuse (catalogue, finalité, limites) ;
    - registre injoignable ou trop lent : indisponible ;
    - réponse corrompue, citoyen inconnu, erreur : échouée ; refus, retrait, expiration par l'usager : refusée ;
    - sinon (réponse obtenue, confirmation, remise…) : réussie."""
    if resultat == "indisponible":
        return "indisponible"
    if evenement == "demande":
        return "autorisée" if resultat == "ok" else "refusée"
    if evenement in ("refus-usager", "retrait", "expiration"):
        return "refusée"
    if resultat == "ok":
        return "réussie"
    return "échouée"


def empreinte(ligne: dict) -> str:
    """Même calcul que journal/verifier.py (clés triées, séparateurs compacts, UTF-8)."""
    # NULL (None) = colonne ajoutée après l'écriture de la ligne : exclue, l'empreinte d'origine reste valable
    sans_hash = {k: v for k, v in ligne.items() if k != "hash" and v is not None}
    canonique = json.dumps(sans_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((ligne["prev_hash"] + canonique).encode("utf-8")).hexdigest()


class Journal:
    def __init__(self, base: sqlite3.Connection, verrou: threading.RLock):
        self._base = base
        self._verrou = verrou
        colonnes = ", ".join(f"{c} TEXT NOT NULL" for c in ("ts",) + CHAMPS + ("prev_hash", "hash"))
        with verrou:
            base.executescript(f"""
                CREATE TABLE IF NOT EXISTS journal (n INTEGER PRIMARY KEY, {colonnes});
                CREATE TRIGGER IF NOT EXISTS journal_sans_modification BEFORE UPDATE ON journal
                    BEGIN SELECT RAISE(ABORT, 'journal en ajout seul'); END;
                CREATE TRIGGER IF NOT EXISTS journal_sans_suppression BEFORE DELETE ON journal
                    BEGIN SELECT RAISE(ABORT, 'journal en ajout seul'); END;
            """)
            # Journal créé avant l'ajout d'une colonne : on l'ajoute (ALTER n'est ni UPDATE ni DELETE ;
            # les anciennes lignes gardent NULL, donc la même empreinte)
            existantes = [c[1] for c in base.execute("PRAGMA table_info(journal)")]
            for colonne in CHAMPS:
                if colonne not in existantes:
                    base.execute(f"ALTER TABLE journal ADD COLUMN {colonne} TEXT")

    def ecrire(self, **champs) -> dict:
        inconnus = set(champs) - set(CHAMPS)
        if inconnus:
            raise ValueError(f"champs inconnus dans le journal : {inconnus}")
        with self._verrou:
            self._base.execute("BEGIN IMMEDIATE")
            try:
                derniere = self._base.execute("SELECT n, hash FROM journal ORDER BY n DESC LIMIT 1").fetchone()
                ligne = {"n": derniere["n"] + 1 if derniere else 1,
                         "ts": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                         **{c: str(champs.get(c, "")) for c in CHAMPS},
                         "statut": champs.get("statut") or statut_de(champs.get("evenement", ""), champs.get("resultat", "")),
                         "prev_hash": derniere["hash"] if derniere else ZEROS}
                ligne["hash"] = empreinte(ligne)
                self._base.execute(f"INSERT INTO journal ({', '.join(ligne)}) VALUES ({', '.join('?' * len(ligne))})",
                                   list(ligne.values()))
                self._base.execute("COMMIT")
            except Exception:
                self._base.execute("ROLLBACK")
                raise
        return ligne

    def lignes_du_sujet(self, sujet: str, limite: int = 100) -> list[dict]:
        with self._verrou:
            lignes = self._base.execute("SELECT * FROM journal WHERE sujet = ? ORDER BY n DESC LIMIT ?",
                                        (sujet, limite)).fetchall()
        return [dict(l) for l in lignes]
