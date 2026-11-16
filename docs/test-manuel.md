# Test manuel : parcours de démonstration pas à pas

Script de démo d'Enock. **Mis à jour à chaque nouvelle fonction** (dernière mise à jour : 16/11 après-midi :
catalogue de démarches, concours direct en une demande, double clé). Toutes les commandes se tapent dans
PowerShell, dans le dossier du dépôt. Toutes les données et tous les comptes sont **fictifs**.

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

| Compte (guichet) | Mot de passe | Service | Démarches proposées (catalogue) |
|---|---|---|---|
| `issa.sawadogo` | `Agent-Demo-2026!` | Direction des concours | **Concours direct adjoints administratifs** (âge 18–37 ans au 31/12/2026 + nationalité + casier, base légale), Vérifier la majorité |
| `awa.ouedraogo` | `Agent-Demo-2026!` | Service des bourses | **Bourse nationale** (nationalité, **avec l'accord de l'usager**), Vérifier la majorité |
| `mariam.kabore` | `Agent-Demo-2026!` | Mairie | Vérifier la majorité (base légale : loi n°012-2025/ALT) |
| `agent.curieux` | `Agent-Demo-2026!` | Service des bourses | (limite de débit : à venir) |

À la **première connexion**, Keycloak montre un QR code : le scanner avec FreeOTP/Aegis, taper le code à
6 chiffres. Ensuite, chaque connexion demande mot de passe + code. (`agent.banc` et `agent.banc.bourses` sont
réservés aux tests automatiques : ne pas les utiliser en démo.)

| Téléphone (USSD) | PIN | Usager | Intérêt |
|---|---|---|---|
| `70000012` | `1234` | BF-0012, Aïssata Diallo | **démo du consentement** (bourse nationale) |
| `70000001` | `1234` | BF-0001, Aminata Kaboré | adulte, tout est « oui » (concours) |
| `70000003` | `1234` | BF-0003, Fatimata Sawadogo | mineure |
| `70000005` / `70000006` | `1234` | Salif Compaoré ×2 | homonymes |
| `70000009` | `1234` | BF-0009, Rasmata Nikiéma | 18 ans le 20/11/2026 |

Citoyens utiles au guichet : `BF-0001` (tout est « oui »), `BF-0003` (mineure, absente du casier), `BF-0004`
(né « vers 1990 »), `BF-0007` (décédée), `BF-0008` (casier non vierge), `BF-0018` (nationalité ivoirienne),
`BF-0019` (doublon), `BF-0099` (inconnu). Détail : `registres_sim/donnees_fictives/LISEZMOI.md`.

## Scène 1 (principale) : le concours direct, ne transmettre que l'utile

1. Guichet → se connecter `issa.sawadogo` (mot de passe + code).
2. Démarche **Concours direct adjoints administratifs**, usager `BF-0001`, Envoyer. Le champ usager est **vide** :
   « exemple : BF-0001 » n'est qu'une indication grisée.
3. Attendu, en UNE demande, 3 registres interrogés en parallèle :
   - « âge de 18 à 37 ans au 31/12/2026 : oui », signé par le registre d'état civil ;
   - « nationalité burkinabè : oui », signé par le registre de la nationalité ;
   - « casier judiciaire vierge : oui », signé par le casier judiciaire ;
   - « **Conclusion : toutes les conditions sont vérifiées.** ». Chaque ligne affiche « Clé du registre : xxxx xxxx xxxx xxxx ».
4. À dire : le guichet n'a reçu ni date de naissance, ni fiche, ni détail du casier. Le registre a répondu
   `{"age_equal_or_over": {"18": true, "38": false}, "date_reference": "2026-12-31"}`, c'est-à-dire « au moins 18 ans,
   pas encore 38 ». Le guichet a revérifié lui-même chaque signature. Les clés se comparent avec :
   `docker compose logs registre-etat-civil registre-nationalite registre-casier | Select-String empreinte`
5. Variantes : `BF-0008` → « casier judiciaire vierge : non » et « au moins une condition n'est pas remplie » ;
   `BF-0018` → « nationalité burkinabè : non » ; `BF-0003` (mineure) → « âge … : non ».
6. **Vérifier la majorité** (au cas où un juré la demande), `BF-0001` → « majeur (18 ans accomplis) : oui ».

## Scène 2 : « Vous voyez avant » (consentement par USSD)

1. Guichet (fenêtre privée) → `awa.ouedraogo`. Démarche **Bourse nationale**, usager `BF-0012`, Envoyer.
2. Attendu : « **En attente de l'usager** … délai : jusqu'à HH h MM ». Rien n'est encore transmis.
3. Onglet téléphone https://usager.griot.test → numéro `70000012` → Allumer → taper `*226#` → PIN `1234`.
4. Menu → `1` (Demandes en attente). Attendu :
   « Le service des bourses recevra : nationalité burkinabè = oui. Rien d'autre. 1. Confirmer 2. Refuser ».
5. Taper `1`. Attendu : « Confirmé. Reçu : xxxx xxxx xxxx xxxx ». **Noter le reçu.**
6. Guichet d'Awa → **Actualiser**. Attendu : « nationalité burkinabè : oui », signature vérifiée.
7. Variante refus : refaire les étapes 1 à 4, puis taper `2` → « Refusé. Rien n'a été transmis. » ; au guichet :
   « nationalité burkinabè : refusé. refusé par l'usager : rien n'a été transmis ».

## Scène 3 : « Vous vérifiez après » (historique et reçu)

1. Téléphone → `0` (menu) → `2` (Qui a consulté mes données). Attendu, 3 lignes par écran :
   « 1. 16/11 12h17 Bourses nation. transmis », « 2. … Bourses nation. accordé » ; `9` = suite.
   Un concours apparaît en une ligne : « Concours 3 infos transmis » (téléphone `70000001`).
2. Taper le numéro d'une ligne (`2` pour « accordé ») : service, finalité, base (« Avec votre accord » ou
   « Base légale »), **Reçu**. Jamais la valeur (« oui ») : le journal ne la contient pas.
3. Vérifier le reçu dans le journal :
   `docker compose exec mediateur python /journal/verifier.py --recu "xxxx xxxx xxxx xxxx"`
   Attendu : « OK Journal intègre : N lignes » puis « OK Reçu retrouvé : ligne …, confirmation (service-bourses) ».
   Un faux reçu (`--recu "0000 0000 0000 0000"`) → « ERREUR Reçu introuvable ».

## Scène 4 : ajouter une démarche sans toucher au code (« Adapter »)

Suivre `docs/AJOUTER_UNE_DEMARCHE.md` : ajouter un bloc dans `catalogue/demarches.yaml`, puis
`docker compose restart mediateur guichet`. La démarche apparaît au guichet. Montrer aussi :
- un catalogue incomplet (supprimer la ligne `texte:` de « Vérifier la majorité ») : le médiateur refuse de démarrer
  et dit pourquoi (`docker compose logs mediateur --tail 5`). **Remettre la ligne** puis relancer ;
- l'empreinte du catalogue écrite au journal à chaque chargement (ligne « catalogue chargé : … sha256 … »).

## Scène 5 : en cas de doute, refuser (jamais deviner)

1. Guichet `issa.sawadogo`, **Vérifier la majorité** : `BF-0004` (né « vers 1990 »), `BF-0007` (décédée),
   `BF-0019` (doublon), `BF-0099` (inconnu).
2. Attendu, toujours le même : « **refusé par le registre d'état civil : réponse impossible, s'adresser à
   l'état civil.** Réponse signée par le registre, signature vérifiée ». Le guichet n'apprend pas pourquoi.
3. Le vrai motif reste dans le registre : `docker compose logs registre-etat-civil --tail 5`
   (« refus (personne décédée) », lié à un numéro de demande, jamais au nom du citoyen).
4. Concours direct, `BF-0003` : le casier répond « réponse impossible, s'adresser au greffe » (absente du casier :
   absent ≠ vierge ; réglable par `absence:` dans `adaptateurs/casier.yaml`, voir `LIMITES.md`).

## Scène 6 : un registre tombe en panne

Faire une demande **Concours direct** au guichet (`issa.sawadogo`, `BF-0001`) après chaque commande :

| Commande | Attendu au guichet, ligne « âge » |
|---|---|
| `python scripts/panne.py etat-civil lent` | après 3 s : « indisponible. Registre d'état civil indisponible (délai dépassé (3 s)), rien n'a été deviné » |
| `python scripts/panne.py etat-civil corrompu` | « refusé. réponse corrompue : signature invalide » (ligne d'alerte au journal) |
| `python scripts/panne.py etat-civil coupe` | « indisponible. Registre d'état civil indisponible (registre injoignable), rien n'a été deviné » |
| `python scripts/panne.py etat-civil normal` | « oui », même empreinte de clé qu'avant |

Pendant la panne, **la nationalité et le casier s'affichent quand même** (signés, vérifiés), et la conclusion dit
« **résultat incomplet, aucune conclusion** » : jamais de « oui » global sur un résultat partiel.
`python scripts/panne.py` affiche l'état des trois registres. **Toujours finir par `normal`.**

## Scène 7 : demander plus que prévu

Le guichet ne propose **que** les démarches du catalogue : aucune question libre, aucune finalité à taper.
Les tentatives hors catalogue (mauvaise finalité, attribut en plus, champ « date_naissance ») se jouent par l'API
(`docs/API.md` et `scripts/demande.py`, à venir). Réponses attendues : « finalité non autorisée » ; « attributs non
autorisés : le catalogue fixe ce que cette démarche peut demander » ; rejet immédiat d'un champ inconnu.
**Double clé** : même si le catalogue laissait la mairie demander le casier, le registre du casier refuserait
lui-même, avec une réponse signée (voir `docs/AJOUTER_UNE_DEMARCHE.md`, § 3).

## Scène 8 : quelqu'un modifie le journal

`python scripts/falsifier_journal.py 5`

Attendu : « Ligne 5 modifiée dans la copie … », puis le vrai journal « OK Journal intègre », puis la copie
« **ERREUR Ligne 5 modifiée** ». (On modifie une copie pour pouvoir rejouer la démo ; la manipulation est celle
d'un administrateur : supprimer le déclencheur SQLite qui interdit les modifications, puis changer la ligne.)

## Scène 9 : wifi coupé

Couper le wifi (et débrancher le câble), puis rejouer la scène 1 ou 2 : tout fonctionne. Aucun service n'a
besoin d'Internet (réseaux Docker internes, certificats locaux, aucune ressource externe).
**À répéter une fois en vrai avant la présentation** (pas encore testé physiquement).

## Après la démo

`python scripts/panne.py` (tout `normal`). Pour tout arrêter sans rien perdre : `docker compose stop`.
