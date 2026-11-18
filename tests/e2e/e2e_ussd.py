"""Test de bout en bout « Vous voyez avant, vous vérifiez après », contre la pile qui tourne.

1. agent.banc.tribunal (tribunal) demande le « Certificat de nationalité » pour BF-0002 : en attente de l'usager.
2. L'usager (téléphone 70000002) compose *226#, voit l'aperçu exact et confirme : il reçoit un reçu.
3. Le guichet actualise : la naissance et la filiation arrivent.
4. L'usager consulte « Qui a consulté mes données » : le reçu y figure, sans la valeur.
5. Une seconde demande est refusée par l'usager : le guichet n'obtient rien.
6. Une troisième est confirmée puis l'accord est retiré avant la remise : le guichet n'obtient rien.

Utilisation :  .venv/Scripts/python tests/e2e/e2e_ussd.py
"""
import html
import re
import sys

import httpx

from e2e_jalon1 import autorite_caddy, connecter
from client_guichet import retirer_les_accords

AGENT = "agent.banc.tribunal"
GUICHET, USSD = "https://guichet.griot.test", "https://usager.griot.test"


def texte(page: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", page)).split())


def demander(guichet: httpx.Client, csrf: str) -> str:
    retirer_les_accords("BF-0002")      # un accord encore valable rendrait la demande immédiate : on le retire d'abord
    r = guichet.post(f"{GUICHET}/demandes", data={"csrf": csrf, "demarche": "certificat-nationalite", "sujet_ref": "BF-0002"})
    assert "En attente de l'usager" in texte(r.text), texte(r.text)[-300:]
    return str(r.url)


class Telephone:
    def __init__(self, client: httpx.Client, numero: str):
        self.client = client
        self.csrf = re.search(r'name="csrf" value="([^"]+)"', client.get(f"{USSD}/").text)[1]
        client.post(f"{USSD}/allumer", data={"csrf": self.csrf, "numero": numero})

    def taper(self, reponse: str) -> str:
        page = self.client.post(f"{USSD}/", data={"csrf": self.csrf, "reponse": reponse}).text
        ecran = html.unescape(re.search(r'<div class="ecran"[^>]*>(.*?)</div>', page, re.S)[1])
        assert len(ecran) <= 160, ecran
        return ecran


def verifier(nom: str, condition: bool, detail: str = "") -> bool:
    print(f"{'OK ' if condition else 'ÉCHEC'} {nom}" + ("" if condition else f"\n      {detail}"))
    return condition


def main():
    retirer_les_accords("BF-0002")             # accord laissé par un passage précédent : on repart de zéro
    ca = autorite_caddy()
    resultats = []
    with httpx.Client(verify=ca, follow_redirects=True, timeout=20) as guichet, \
         httpx.Client(verify=ca, follow_redirects=True, timeout=20) as telephone:
        csrf = connecter(guichet, AGENT)
        tel = Telephone(telephone, "70000002")
        tel.taper("*226#")
        tel.taper("1234")
        # Nettoyage : refuse les demandes laissées en attente par un passage précédent interrompu
        while "recevra" in tel.taper("1"):
            tel.taper("2")
            tel.taper("0")
        tel.taper("0")       # « Aucune demande en attente. 0. Menu » -> retour au menu

        adresse = demander(guichet, csrf)
        resultats.append(verifier("demande de certificat de nationalité en attente de l'usager", True))
        apercu = tel.taper("1")
        resultats.append(verifier("aperçu exact sur le téléphone",
                                  "Le tribunal recevra : naissance" in apercu, apercu))
        confirmation = tel.taper("1")
        recu = re.search(r"Reçu : ((?:[0-9a-f]{4} ){3}[0-9a-f]{4})", confirmation)
        resultats.append(verifier(f"confirmation avec reçu ({recu[1] if recu else '?'})", bool(recu), confirmation))

        page = texte(guichet.get(adresse).text)
        resultats.append(verifier("guichet : naissance et filiation, via la passerelle",
                                  "Fourni par le registre d'état civil via la passerelle" in page, page[-300:]))

        tel.taper("0")
        historique = tel.taper("2")
        resultats.append(verifier("historique : la consultation apparaît, sans la valeur",
                                  "Tribunal naissance transmis" in historique and "Tribunal naissance accordé" in historique
                                  and "oui" not in historique, historique))
        detail = tel.taper("2")        # ligne 1 : « transmis » ; ligne 2 : « accordé », celle du reçu
        resultats.append(verifier("détail : finalité, base et le même reçu",
                                  "délivrance d'un certificat de nationalité" in detail and bool(recu) and recu[1] in detail
                                  and "Avec votre accord" in detail, detail))
        tel.taper("0")       # détail -> liste
        tel.taper("0")       # liste -> menu

        adresse = demander(guichet, csrf)
        tel.taper("1")
        refus = tel.taper("2")
        page = texte(guichet.get(adresse).text)
        resultats.append(verifier("refus de l'usager : le guichet n'obtient rien",
                                  "refusé par l'usager : rien n'a été transmis" in page and "Fourni par le registre d'état civil" not in page,
                                  refus + " | " + page[-200:]))
        # 6. Retrait de l'accord AVANT que le guichet ne récupère la réponse : rien ne part
        tel.taper("0")
        adresse = demander(guichet, csrf)
        tel.taper("1")
        tel.taper("1")                 # confirme
        tel.taper("0")
        tel.taper("3")                 # Retirer un accord (le plus récent en premier)
        tel.taper("1")
        retrait = tel.taper("1")
        page = texte(guichet.get(adresse).text)
        resultats.append(verifier("retrait de l'accord avant la remise : le guichet n'obtient rien",
                                  "Accord retiré. Rien n'a été transmis" in retrait
                                  and "accord retiré par l'usager" in page and "Fourni par le registre d'état civil" not in page,
                                  retrait + " | " + page[-200:]))
    sys.exit(0 if all(resultats) else 1)


if __name__ == "__main__":
    main()
