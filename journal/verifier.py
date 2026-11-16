"""Vérifie l'intégrité du journal chaîné du médiateur, et éventuellement un reçu.

Utilisation (le journal est dans le volume du médiateur) :
    docker compose exec mediateur python /journal/verifier.py
    docker compose exec mediateur python /journal/verifier.py --recu "9035 47b3 1c2e 9f04"
    docker compose exec mediateur python /journal/verifier.py --registres     (double trace)

Pour chaque ligne, dans l'ordre : recalcule hash = SHA-256(prev_hash + JSON canonique de la ligne
sans « hash ») et vérifie que prev_hash est bien l'empreinte de la ligne précédente.
Un reçu (les 16 premiers caractères de l'empreinte, avec ou sans espaces) doit se retrouver dans le journal :
si un administrateur avait recalculé toute la chaîne, les reçus déjà remis ne correspondraient plus.

Double trace (--registres) : chaque registre garde SA liste des réponses qu'il a signées (dans son volume,
hors de portée du médiateur) et l'exporte signée. On la compare au journal : une réponse du registre absente
du journal = une consultation cachée par le médiateur, même si la chaîne a été entièrement recalculée.
"""
import argparse
import hashlib
import json
import sqlite3
import sys

ZEROS = "0" * 64


def empreinte(ligne: dict) -> str:
    """Même calcul que mediateur/app/journal.py (clés triées, séparateurs compacts, UTF-8)."""
    sans_hash = {k: v for k, v in ligne.items() if k != "hash"}
    canonique = json.dumps(sans_hash, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256((ligne["prev_hash"] + canonique).encode("utf-8")).hexdigest()


def verifier(chemin: str) -> tuple[bool, str, list[dict]]:
    base = sqlite3.connect(f"file:{chemin}?mode=ro", uri=True)    # lecture seule
    base.row_factory = sqlite3.Row
    lignes = [dict(l) for l in base.execute("SELECT * FROM journal ORDER BY n")]
    precedente = ZEROS
    for attendu, ligne in enumerate(lignes, start=1):
        if ligne["n"] != attendu:
            return False, f"Ligne {attendu} supprimée (on passe directement à la ligne {ligne['n']})", lignes
        if empreinte(ligne) != ligne["hash"]:
            return False, f"Ligne {attendu} modifiée", lignes
        if ligne["prev_hash"] != precedente:
            return False, f"Ligne {attendu - 1} modifiée (son empreinte a été recalculée : chaînage rompu)", lignes
        precedente = ligne["hash"]
    return True, f"Journal intègre : {len(lignes)} lignes", lignes


REGISTRES = ("etat-civil", "nationalite", "casier")


def traces_des_registres() -> dict[str, dict | str]:
    """Trace SIGNÉE de chaque registre, vérifiée avec sa clé publique (volume du registre, lecture seule).
    Renvoie {registre: {"debut": ..., "trace": [...]}} ou {registre: "motif de l'échec"}."""
    import httpx       # importés ici : la vérification simple du journal n'a besoin que de la bibliothèque standard
    import jwt
    traces = {}
    for registre in REGISTRES:
        try:
            r = httpx.get(f"http://registre-{registre}:8000/trace", timeout=5)
            cle = open(f"/publiques/{registre}/cle.pem", "rb").read()
            traces[registre] = jwt.decode(r.json()["jeton"], cle, algorithms=["EdDSA"], audience="verification",
                                          issuer=f"registre-{registre}")
        except (httpx.HTTPError, OSError, ValueError, KeyError, jwt.PyJWTError) as e:
            traces[registre] = f"trace illisible ou non signée ({type(e).__name__}) : comparaison impossible"
    return traces


def comparer(traces: dict, lignes: list[dict]) -> list[str]:
    """Écarts entre les traces des registres et le journal du médiateur (liste vide = concordance)."""
    debut_journal = lignes[0]["ts"] if lignes else ""
    ecarts = []
    for registre, export in traces.items():
        if isinstance(export, str):
            ecarts.append(f"{registre} : {export}")
            continue
        debut = max(debut_journal, export["debut"])            # période couverte par les DEUX traces
        # Journal : toute ligne où le médiateur dit avoir reçu (ou attendu en vain) une réponse de ce registre
        vu_au_journal = {(l["id_demande"], l["attribut"]) for l in lignes
                         if l["registre"] == registre and l["evenement"] in ("reponse-registre", "alerte")
                         and l.get("id_demande") and l["ts"] >= debut}
        recu_selon_journal = {(l["id_demande"], l["attribut"]) for l in lignes
                              if l["registre"] == registre and l["evenement"] == "reponse-registre"
                              and l["resultat"] in ("ok", "refuse") and l.get("id_demande") and l["ts"] >= debut}
        emis_par_registre = {(t["id_demande"], t["attribut"]) for t in export["trace"] if t["ts"] >= debut}
        for id_demande, attribut in sorted(emis_par_registre - vu_au_journal):
            ecarts.append(f"{registre} : réponse à la demande {id_demande} ({attribut}) ABSENTE du journal du médiateur")
        for id_demande, attribut in sorted(recu_selon_journal - emis_par_registre):
            ecarts.append(f"{registre} : le journal cite une réponse à la demande {id_demande} ({attribut}) "
                          "que le registre n'a jamais émise")
    return ecarts


def main():
    parser = argparse.ArgumentParser(description="Vérifie le journal chaîné du médiateur.")
    parser.add_argument("chemin", nargs="?", default="/donnees/mediateur.sqlite3")
    parser.add_argument("--recu", help="reçu : 16 caractères hexadécimaux, avec ou sans espaces")
    parser.add_argument("--registres", action="store_true",
                        help="double trace : compare le journal aux traces signées des registres")
    args = parser.parse_args()

    integre, message, lignes = verifier(args.chemin)
    print(("OK  " if integre else "ERREUR  ") + message)
    if args.recu:
        recu = args.recu.replace(" ", "").lower()
        # 16 caractères = 64 bits : impossible en pratique de fabriquer une ligne dont l'empreinte commence pareil
        if len(recu) < 16 or any(c not in "0123456789abcdef" for c in recu):
            sys.exit("Un reçu compte 16 caractères hexadécimaux (par exemple « 9035 47b3 1c2e 9f04 »).")
        trouvees = [l for l in lignes if l["hash"].startswith(recu)]
        if trouvees:
            l = trouvees[0]
            print(f"OK  Reçu retrouvé : ligne {l['n']}, {l['ts']}, {l['evenement']} ({l['demandeur']})")
        else:
            print("ERREUR  Reçu introuvable : le journal a été réécrit ou le reçu est faux")
            integre = False
    if args.registres:
        traces = traces_des_registres()
        ecarts = comparer(traces, lignes)
        for registre, export in traces.items():
            if not isinstance(export, str):
                print(f"    trace du registre {registre} : {len(export['trace'])} réponses signées, signature vérifiée")
        if ecarts:
            for ecart in ecarts:
                print(f"ERREUR  {ecart}")
            integre = False
        else:
            print("OK  Double trace concordante : chaque réponse des registres figure au journal, et inversement")
    sys.exit(0 if integre else 1)


if __name__ == "__main__":
    main()
