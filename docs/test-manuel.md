# Test manuel : parcours de démonstration pas à pas

Script de démo d'Enock. **Mis à jour à chaque nouvelle fonction** (dernière mise à jour : 16/11, phase 2 :
3 registres, USSD, pannes). Toutes les commandes se tapent dans PowerShell, dans le dossier du dépôt.
Toutes les données et tous les comptes sont **fictifs**.

## 0. Préparation (une fois, avant la démo)

1. Fichier hosts (`C:\Windows\System32\drivers\etc\hosts`, Bloc-notes lancé en administrateur) :
   `127.0.0.1 guichet.griot.test usager.griot.test auth.griot.test`
2. Démarrer : `docker compose up -d --wait` (9 services « healthy » : `docker compose ps`).
3. Faire confiance au HTTPS local (sinon le navigateur affiche un avertissement) :
   `docker compose cp caddy:/data/caddy/pki/authorities/local/root.crt caddy-racine.crt`, double-cliquer sur
   `caddy-racine.crt` → Installer le certificat → Utilisateur actuel → « Autorités de certification racines de
   confiance ». Redémarrer le navigateur. (`caddy-racine.crt` n'est jamais commité.)
4. Registres en état normal : `python scripts/panne.py` doit afficher `normal` trois fois.
5. Sur le téléphone de démo, installer **FreeOTP** ou **Aegis** (applications libres) pour le code TOTP.
6. Ouvrir trois onglets : https://guichet.griot.test (agent), une fenêtre privée sur https://guichet.griot.test
   (second agent), https://usager.griot.test (téléphone de l'usager).

## Comptes de démonstration

| Compte (guichet) | Mot de passe | Service | Démarches proposées |
|---|---|---|---|
| `awa.ouedraogo` | `Agent-Demo-2026!` | Service des bourses | bourse (majeur), bourse (nationalité) : **avec l'accord de l'usager** |
| `issa.sawadogo` | `Agent-Demo-2026!` | Direction des concours | concours (majeur), concours (nationalité), concours (casier) : **base légale** |
| `mariam.kabore` | `Agent-Demo-2026!` | Mairie | publication des bans (majeur) : base légale |
| `agent.curieux` | `Agent-Demo-2026!` | Service des bourses | (limite de débit : à venir) |

À la **première connexion**, Keycloak montre un QR code : le scanner avec FreeOTP/Aegis, taper le code à
6 chiffres. Ensuite, chaque connexion demande mot de passe + code. (`agent.banc` et `agent.banc.bourses` sont
réservés aux tests automatiques : ne pas les utiliser en démo.)

| Téléphone (USSD) | PIN | Usager | Intérêt |
|---|---|---|---|
| `70000012` | `1234` | BF-0012, Aïssata Diallo | **démo du consentement** (bourse) |
| `70000001` | `1234` | BF-0001, Aminata Kaboré | adulte, casier vierge |
| `70000003` | `1234` | BF-0003, Fatimata Sawadogo | mineure |
| `70000005` / `70000006` | `1234` | Salif Compaoré ×2 | homonymes |
| `70000009` | `1234` | BF-0009, Rasmata Nikiéma | 18 ans le 20/11/2026 |

Citoyens utiles au guichet : `BF-0001` (tout est « oui »), `BF-0003` (mineure), `BF-0004` (né « vers 1990 »),
`BF-0007` (décédée), `BF-0008` (casier non vierge), `BF-0018` (nationalité ivoirienne), `BF-0019` (doublon),
`BF-0099` (inconnu). Détail : `registres_sim/donnees_fictives/LISEZMOI.md`.

## Scène 1 : « majeur : oui », et rien d'autre (base légale)

1. Guichet → se connecter `issa.sawadogo` (mot de passe + code).
2. Démarche **Inscription à un concours de la fonction publique**, usager `BF-0001`, Envoyer.
3. Attendu : **« majeur : oui »**, « Signé par le registre d'état civil, signature vérifiée, valable jusqu'à
   HH h MM », « Clé du registre : xxxx xxxx xxxx xxxx ».
4. À dire : le guichet n'a reçu ni date de naissance ni fiche ; il a lui-même revérifié la signature du
   registre. L'empreinte de clé se compare avec : `docker compose logs registre-etat-civil | Select-String empreinte`

## Scène 2 : « Vous voyez avant » (consentement par USSD)

1. Guichet (fenêtre privée) → `awa.ouedraogo`. Démarche **Demande de bourse**, usager `BF-0012`, Envoyer.
2. Attendu : « **En attente de l'usager** … délai : jusqu'à HH h MM ». Rien n'est encore transmis.
3. Onglet téléphone https://usager.griot.test → numéro `70000012` → Allumer → taper `*226#` → PIN `1234`.
4. Menu → `1` (Demandes en attente). Attendu :
   « Le service des bourses recevra : majeur = oui. Rien d'autre. 1. Confirmer 2. Refuser ».
5. Taper `1`. Attendu : « Confirmé. Reçu : xxxx xxxx xxxx xxxx ». **Noter le reçu.**
6. Guichet d'Awa → **Actualiser**. Attendu : « majeur : oui », signature vérifiée.
7. Variante refus : refaire 1-4, taper `2` → « Refusé. Rien n'a été transmis. » ; au guichet :
   « Refusé : refusé par l'usager : rien n'a été transmis ».

## Scène 3 : « Vous vérifiez après » (historique et reçu)

1. Téléphone → `0` (menu) → `2` (Qui a consulté mes données). Attendu, 3 lignes par écran :
   « 1. 16/11 12h17 Bourses majeur transmis », « 2. … Bourses majeur accordé » ; `9` = suite.
2. Taper le numéro d'une ligne (`2` pour « accordé ») : service, finalité, base (« Avec votre accord » ou
   « Base légale »), **Reçu**. Jamais la valeur (« oui ») : le journal ne la contient pas.
3. Vérifier le reçu dans le journal :
   `docker compose exec mediateur python /journal/verifier.py --recu "xxxx xxxx xxxx xxxx"`
   Attendu : « OK Journal intègre : N lignes » puis « OK Reçu retrouvé : ligne …, confirmation (service-bourses) ».
   Un faux reçu (`--recu "0000 0000 0000 0000"`) → « ERREUR Reçu introuvable ».

## Scène 4 : ne transmettre que l'utile (casier, nationalité)

1. Guichet `issa.sawadogo` → **Concours (casier judiciaire)**, usager `BF-0008` → « casier judiciaire vierge : non ».
2. Montrer `registres_sim/donnees_fictives/casier.csv` : la fiche contient « vol (2019) ; escroquerie (2022) ».
   Rien de cela n'arrive au guichet.
3. **Concours (nationalité)**, `BF-0018` → « nationalité burkinabè : non » ; `BF-0001` → « oui ».

## Scène 5 : en cas de doute, refuser (jamais deviner)

1. Guichet `issa.sawadogo`, concours (majeur) : `BF-0004` (né « vers 1990 »), `BF-0007` (décédée),
   `BF-0019` (doublon), `BF-0099` (inconnu).
2. Attendu, toujours le même : « **Refusé par le registre d'état civil : réponse impossible, s'adresser à
   l'état civil.** Réponse signée par le registre, signature vérifiée ». Le guichet n'apprend pas pourquoi.
3. Le vrai motif reste dans le registre : `docker compose logs registre-etat-civil --tail 5`
   (« refus (personne décédée) », lié à un numéro de demande, jamais au nom du citoyen).
4. Casier `BF-0003` (absente du casier) → « réponse impossible, s'adresser au greffe » : absent ≠ vierge.

## Scène 6 : un registre tombe en panne

Faire une demande au guichet (`issa.sawadogo`, concours, `BF-0001`) après chaque commande :

| Commande | Attendu au guichet |
|---|---|
| `python scripts/panne.py etat-civil lent` | après 3 s : « Registre indisponible (délai dépassé (3 s)), rien n'a été deviné » |
| `python scripts/panne.py etat-civil corrompu` | « Refusé : réponse corrompue : signature invalide » (ligne d'alerte au journal) |
| `python scripts/panne.py etat-civil coupe` | « Registre indisponible (registre injoignable), rien n'a été deviné » |
| `python scripts/panne.py etat-civil normal` | « majeur : oui », même empreinte de clé qu'avant |

Pendant la panne de l'état civil, **concours (casier)** fonctionne toujours : un registre en panne ne bloque
pas les autres. `python scripts/panne.py` affiche l'état des trois registres. **Toujours finir par `normal`.**

## Scène 7 : mauvaise finalité

Guichet `issa.sawadogo`, concours, `BF-0001`, ouvrir « Autre finalité (test du refus) », taper `curiosité`
→ « Refusé : finalité non autorisée ». Le registre n'est pas appelé ; la tentative apparaît dans l'historique
de l'usager (téléphone `70000001`, menu 2 : « refusé »).

## Scène 8 : quelqu'un modifie le journal

`python scripts/falsifier_journal.py 5`

Attendu : « Ligne 5 modifiée dans la copie … », puis le vrai journal « OK Journal intègre », puis la copie
« **ERREUR Ligne 5 modifiée** ». (On modifie une copie pour pouvoir rejouer la démo ; la manipulation est celle
d'un administrateur : supprimer le déclencheur SQLite qui interdit les modifications, puis changer la ligne.)

## Scène 9 : wifi coupé

Couper le wifi (et débrancher le câble), puis rejouer la scène 1 ou 2 : tout fonctionne. Aucun service n'a
besoin d'Internet (réseaux Docker internes, certificats locaux, aucune ressource externe).

## Après la démo

`python scripts/panne.py` (tout `normal`). Pour tout arrêter sans rien perdre : `docker compose stop`.
