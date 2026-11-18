"""Test de bout en bout du portail web usager (https://usager.griot.test/portail), contre la pile qui tourne.

1. agent.banc.tribunal (tribunal) demande le « certificat de nationalité » pour BF-0008 : en attente de l'usager.
2. L'usager se connecte au portail (70000008 + PIN), voit l'aperçu exact et confirme : il reçoit un reçu.
3. Le guichet actualise : la naissance et la filiation arrivent.
4. La même confirmation est visible dans l'historique USSD (*226#), marquée « (web) », avec le même reçu.
5. Le détail web montre finalité, base, « Fait depuis : le portail web » et le reçu ; verifier.py retrouve le reçu.
6. Pages légères : aucun script, aucune ressource externe.

Utilisation :  .venv/Scripts/python tests/e2e/e2e_portail.py
"""
import re
import subprocess
import sys

import httpx

from e2e_jalon1 import RACINE, autorite_caddy, connecter
from client_guichet import retirer_les_accords
from e2e_ussd import Telephone, texte, verifier

AGENT = "agent.banc.tribunal"
GUICHET, PORTAIL = "https://guichet.griot.test", "https://usager.griot.test/portail"
NUMERO, SUJET = "70000008", "BF-0008"


def jeton(page: str) -> str:
    return re.search(r'name="csrf" value="([^"]+)"', page)[1]


def main():
    retirer_les_accords("BF-0008")             # accord laissé par un passage précédent : on repart de zéro
    ca = autorite_caddy()
    resultats = []
    with httpx.Client(verify=ca, follow_redirects=True, timeout=20) as guichet, \
         httpx.Client(verify=ca, follow_redirects=True, timeout=20) as web, \
         httpx.Client(verify=ca, follow_redirects=True, timeout=20) as telephone:
        csrf_guichet = connecter(guichet, AGENT)

        accueil = web.get(PORTAIL)
        resultats.append(verifier("page de connexion légère, sans script ni ressource externe",
                                  accueil.status_code == 200 and "<script" not in accueil.text
                                  and "https://" not in accueil.text and len(accueil.content) < 4000,
                                  f"{accueil.status_code} {len(accueil.content)} octets"))
        page = web.post(f"{PORTAIL}/connexion", data={"csrf": jeton(accueil.text), "numero": NUMERO, "pin": "1234"}).text
        csrf = jeton(page)
        # Nettoyage : refuse les demandes laissées en attente par un passage précédent interrompu
        for ancienne in re.findall(r'/portail/attente/([0-9a-f-]+)/refuser', web.get(f"{PORTAIL}/attente").text):
            web.post(f"{PORTAIL}/attente/{ancienne}/refuser", data={"csrf": csrf})

        r = guichet.post(f"{GUICHET}/demandes", data={"csrf": csrf_guichet, "demarche": "certificat-nationalite", "sujet_ref": SUJET})
        adresse = str(r.url)
        resultats.append(verifier("demande de certificat de nationalité en attente de l'usager", "En attente de l'usager" in texte(r.text),
                                  texte(r.text)[-300:]))

        attente = web.get(f"{PORTAIL}/attente").text
        resultats.append(verifier("aperçu exact sur le portail",
                                  "Le tribunal recevra : naissance" in texte(attente),
                                  texte(attente)[-300:]))
        id_demande = re.search(r'/portail/attente/([0-9a-f-]+)/confirmer', attente)[1]
        confirmation = texte(web.post(f"{PORTAIL}/attente/{id_demande}/confirmer", data={"csrf": csrf}).text)
        recu = re.search(r"Reçu : ((?:[0-9a-f]{4} ){3}[0-9a-f]{4})", confirmation)
        resultats.append(verifier(f"confirmation web avec reçu ({recu[1] if recu else '?'})", bool(recu), confirmation))

        page = texte(guichet.get(adresse).text)
        resultats.append(verifier("guichet : naissance et filiation, via la passerelle",
                                  "Fourni par le registre d'état civil via la passerelle"
                                  in page, page[-300:]))

        tel = Telephone(telephone, NUMERO)
        tel.taper("*226#")
        tel.taper("1234")
        historique = tel.taper("2")
        lignes = historique.splitlines()
        numero = next((l[0] for l in lignes if "accordé" in l), None)
        detail = tel.taper(numero) if numero else ""
        resultats.append(verifier("USSD : la confirmation faite sur le web apparaît, « (web) », même reçu",
                                  "accordé (web)" in detail and bool(recu) and recu[1] in detail, historique + " | " + detail))

        liste = web.get(f"{PORTAIL}/historique").text
        lien = re.search(r'/portail/historique/(\d+)">\s*<span class="petit">[^<]*</span><br>\s*<strong>[^<]*</strong>[^<]*'
                         r'<span class="etat confirmation">', liste)
        detail_web = texte(web.get(f"{PORTAIL}/historique/{lien[1]}").text) if lien else ""
        resultats.append(verifier("détail web : finalité, base, canal et le même reçu, sans la valeur",
                                  "délivrance d'un certificat de nationalité" in detail_web and "Avec votre accord" in detail_web
                                  and "le portail web" in detail_web and bool(recu) and recu[1] in detail_web
                                  and "= oui" not in detail_web, detail_web[-400:]))

        if recu:
            sortie = subprocess.run(["docker", "compose", "exec", "-T", "mediateur", "python", "/journal/verifier.py",
                                     "--recu", recu[1]], cwd=RACINE, capture_output=True, text=True, encoding="utf-8").stdout
            resultats.append(verifier("verifier.py retrouve le reçu dans un journal intègre",
                                      "Journal intègre" in sortie and "trouvé" in sortie.lower(), sortie))
    sys.exit(0 if all(resultats) else 1)


if __name__ == "__main__":
    main()
