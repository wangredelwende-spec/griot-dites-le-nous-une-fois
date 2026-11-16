# Test manuel : parcours de démonstration pas à pas

Script de démo d'Enock. **Mis à jour à chaque nouvelle fonction** (dernière mise à jour : 16/11 soir :
scénario principal = passeport ordinaire, avec l'accord de l'usager). Toutes les commandes se tapent dans
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
7. Enrôler une fois le TOTP des comptes de démo (QR code à la première connexion) : `moussa.kone` (passeport),
   `issa.sawadogo`, `awa.ouedraogo`, `agent.curieux`, `controle.cil`.

8. Sauvegarde hors ligne des images (après chaque reconstruction, tant qu'on a le réseau) :
   `python scripts\sauvegarder_hors_ligne.py` → `hors_ligne\griot-images-<date>.tar` (environ 560 Mo, 8 images
   dont l'OCR). Sans réseau, ou sur une autre machine : `python scripts\charger_hors_ligne.py hors_ligne\griot-images-<date>.tar`
   (vérifie l'empreinte SHA-256, `docker load`, puis démarre sans rien construire ni télécharger, environ 2 minutes).

## 0 bis. Juste avant CHAQUE répétition et avant la démo

1. Comptes de test désactivés : dans `.env`, `OUTILS_TEST=0` (sinon : le mettre à 0 puis `python scripts\outils_test.py`).
2. Journal neuf (l'ancien est **archivé**, jamais effacé) :
   ```powershell
   cd C:\Users\USER\Desktop\HACKATON_2026
   python scripts\remise_a_zero.py --oui
   ```
   Attendu à la fin : « Journal intègre : 1 lignes » puis « Archive … conservée et vérifiable ».
3. `python scripts\panne.py` → `normal` trois fois. Page Contrôle (`controle.cil`) : « comptes de test actifs : non ».

## Comptes de démonstration

| Compte (guichet) | Mot de passe | Service | Démarches proposées (catalogue) |
|---|---|---|---|
| `moussa.kone` | `Agent-Demo-2026!` | Service des passeports – ONI (ministère de la Sécurité) | **Passeport ordinaire** (majeur + nationalité + interdiction de sortie du territoire, **avec l'accord de l'usager**) : scène 1 |
| `issa.sawadogo` | `Agent-Demo-2026!` | Direction des concours – ministère des Serviteurs du peuple | **Concours direct adjoints administratifs** (âge 18–37 ans au 31/12/2026 + nationalité + casier, base légale), Vérifier la majorité |
| `awa.ouedraogo` | `Agent-Demo-2026!` | Service des bourses | **Bourse nationale** (nationalité, **avec l'accord de l'usager**), Vérifier la majorité |
| `mariam.kabore` | `Agent-Demo-2026!` | Mairie | Vérifier la majorité (base légale : loi n°012-2025/ALT) |
| `agent.curieux` | `Agent-Demo-2026!` | Service des bourses | Vérifier la majorité : **démo de la limite de débit** (scène 2 bis) |
| `controle.cil` | `Controle-Demo-2026!` | Contrôle (lecture seule, rôle `controleur`) | Aucune démarche : page **Contrôle** (scène 2 ter) |

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

## Scène 1 (principale) : le passeport, « vous voyez avant »

Aujourd'hui, pour un passeport ordinaire (passeport AES produit par l'ONI), l'usager apporte au service des
passeports acte de naissance, certificat de nationalité, CNIB et extrait de casier, en copies légalisées (plus une
autorisation parentale pour un mineur). Ici, c'est **lui qui demande** que les preuves soient récupérées à sa place.

1. Guichet → se connecter `moussa.kone` (mot de passe + code).
2. Démarche **Passeport ordinaire**, usager `BF-0001`, Envoyer → « **En attente de l'usager** ». Rien n'est encore
   transmis au guichet.
3. Téléphone `70000001`, PIN `1234`, `*226#` → `1` : « L'ONI (passeports) recevra : majeur = oui ;
   burkinabè = oui ; interdiction de sortie du territoire = non. Rien d'autre. 1. Confirmer 2. Refuser ».
4. `1` → « Confirmé. Reçu : xxxx xxxx xxxx xxxx » (à noter : il servira en scène 3).
5. Guichet → **Actualiser** : majeur : oui, burkinabè : oui, interdiction de sortie du territoire : non, chacun
   signé par SON registre, signature vérifiée ; « Conclusion : toutes les conditions sont vérifiées ».
6. À dire : l'ONI ne reçoit ni date de naissance, ni filiation, ni le casier. Elle n'apprend même pas si le
   casier est vierge : seulement s'il existe une **interdiction de sortie du territoire** (peine complémentaire).
   Variante `BF-0005` (Salif, condamné pour vol, sans interdiction) : « interdiction : non ». Le vol ne regarde pas
   le service des passeports.
7. Variantes :
   - `BF-0009` (Rasmata, 18 ans le 20/11, téléphone `70000009`) → « **mineur : autorisation parentale requise** ».
     Ce n'est pas un refus : c'est une réponse signée « majeur = non ». (Consentement par le représentant légal :
     feuille de route.)
   - `BF-0008` → « interdiction de sortie du territoire : oui » ; « au moins une condition n'est pas remplie ».
   - Au téléphone, `2` (Refuser) → au guichet « refusé par l'usager : rien n'a été transmis ».

## Scène 1 bis : la preuve que rien ne fuit

`python scripts/preuve_minimisation.py BF-0008` (le jury peut choisir un autre citoyen)

Attendu :
1. Données témoins lues DANS les registres : nom, date et lieu de naissance, parents, détail du casier (« vol… »).
2. Une vraie demande « Concours direct » de bout en bout.
3. Chaque témoin est cherché hors des registres (base SQLite du médiateur, historique de l'usager, page du guichet,
   réponses reçues, logs du médiateur, du guichet, de l'USSD et de Caddy) : **« introuvable ✅ » partout**.
4. Les réponses signées reçues par le guichet, décodées en entier : `{"age_equal_or_over": {"18": true, "38": true},
   "date_reference": "2026-12-31", …}` (47 ans : trop âgé), `"casier_judiciaire_vierge": false`. Rien d'autre.
Au guichet, chaque résultat a aussi un bouton « réponse signée reçue (contenu complet, décodé) ».

## Scène 1 ter (secondaire) : le concours direct, base légale et panne partielle sur 3 registres

Pas d'accord à demander : la consultation est prévue par le communiqué du concours (base légale), mais elle
apparaît dans l'historique de l'usager avec le texte cité.

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
8. Variante **retrait** : refaire 1 à 5 (confirmer), puis AVANT qu'Awa actualise : `0` → `3` (Retirer un accord)
   → `1` → `1`. Attendu : « Accord retiré. Rien n'a été transmis. Reçu : … ». Awa actualise :
   « accord retiré par l'usager : rien n'a été transmis ». Si Awa avait déjà reçu la réponse, le téléphone dit
   « Accord retiré. Déjà transmis : le service ne doit plus l'utiliser » (écrit au journal, on ne peut pas rappeler
   une réponse déjà remise).
9. Variante **expiration** : ne rien faire pendant 10 minutes ; Awa actualise : « Délai dépassé ».

## Scène 2 bis : l'agent curieux est bloqué

1. Guichet → `agent.curieux`. **Vérifier la majorité** pour `BF-0001`, `BF-0002`, `BF-0005`, `BF-0006`, `BF-0011`
   (5 citoyens différents) : tout passe.
2. Un 6e citoyen, `BF-0012` → « **bloqué** : agent bloqué : plus de 5 citoyens différents consultés en 60 minutes,
   consultation à contrôler ». Le registre n'est même pas appelé.
3. Téléphone `70000001` (Aminata, BF-0001) → `2` : « … Bourses âge ALERTE » ; le détail donne le motif.
   Chaque citoyen consulté par cet agent a reçu l'alerte.
4. Autre limite : un même service ne peut pas faire plus de 5 demandes sur la même personne en 24 h.
(Limites réglables dans `docker-compose.yml` : `LIMITE_SUJETS`, `FENETRE_LIMITE`, `LIMITE_PAR_CITOYEN`.)

## Scène 2 ter : le contrôle voit l'alerte (lecture seule)

1. Guichet → se déconnecter, puis `controle.cil` (mot de passe + TOTP) : on arrive sur
   `https://guichet.griot.test/controle`.
2. En haut : nombre d'alertes, registres joignables (3 / 3), **comptes de test actifs : non** (doit être « non »
   pendant la démo).
3. **Alertes** : « agent.curieux … Alerte : agent bloqué … (6 citoyens concernés) ». On voit l'agent et le
   service, jamais les citoyens (ni identifiant, ni pseudonyme, ni réponse).
4. **État des registres** : couper un registre (`python scripts/panne.py casier coupe`), actualiser : « en panne ».
   Remettre : `python scripts/panne.py casier normal`.
5. **Vérifier le journal** : même vérification que `verifier.py --registres` (chaîne + double trace).
6. **Catalogue en vigueur** : démarches, qui peut demander quoi, et ce que chaque registre accepte (double clé),
   avec l'empreinte SHA-256 écrite au journal.
7. Le contrôleur ne peut rien faire d'autre : l'adresse `/` le renvoie vers `/controle`, et le médiateur refuse
   ses demandes (pas de rôle `agent-guichet`).

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
lui-même, avec une réponse signée (voir `docs/AJOUTER_UNE_DEMARCHE.md`, § 3). Idem pour un seuil d'âge non déclaré
par le registre (« 25 ans ? 26 ans ? … ») : « paramètres non autorisés par le registre pour ce service ».
**Médiateur compromis** : un appel direct au registre sans jeton d'agent valide est refusé par le registre :
`docker compose exec mediateur python -c "import httpx; print(httpx.post('http://registre-casier:8000/attributs', json={'id_demande': 'x', 'attribut': 'casier_judiciaire_vierge', 'sujet_ref': 'BF-0008', 'destinataire': 'direction-concours'}).json())"`
→ un jeton signé dont le contenu est « refus : jeton d'agent absent ».
**Trop de demandes sur une même personne** : au-delà de 5 demandes d'un même service en 24 h → « bloqué » au guichet
et « ALERTE » dans l'historique USSD du citoyen (motif affiché dans le détail).

## Scène 8 : quelqu'un modifie le journal

`python scripts/falsifier_journal.py 5`

Attendu : « Ligne 5 modifiée dans la copie … », puis le vrai journal « OK Journal intègre », puis la copie
« **ERREUR Ligne 5 modifiée** ». (On modifie une copie pour pouvoir rejouer la démo ; la manipulation est celle
d'un administrateur : supprimer le déclencheur SQLite qui interdit les modifications, puis changer la ligne.)

**Plus fort : l'administrateur habile** qui supprime une consultation ET recalcule toute la chaîne :
`python scripts/falsifier_journal.py --cacher`

Attendu : la copie falsifiée « OK Journal intègre : N lignes » (la chaîne seule ne voit rien !), puis, avec la
**double trace** : « ERREUR etat-civil : réponse à la demande … ABSENTE du journal du médiateur » (idem nationalité
et casier). Chaque registre garde chez lui la liste des réponses qu'il a signées (jamais la valeur) ; le médiateur
ne peut pas y toucher. Sur le vrai journal :
`docker compose exec mediateur python /journal/verifier.py --registres` → « OK Double trace concordante ».

## Scène 9 : wifi coupé

Couper le wifi (et débrancher le câble), puis rejouer la scène 1 ou 2 : tout fonctionne. Aucun service n'a
besoin d'Internet (réseaux Docker internes, certificats locaux, aucune ressource externe).
**À répéter une fois en vrai avant la présentation** (pas encore testé physiquement).

## Scène 10 : les données du jury (format inconnu, configuration seulement)

Procédure complète : `docs/JOUR_J_DONNEES_JURY.md`. À montrer : `inspecter_donnees.py … --proposer-yaml` sur un
fichier du jury, puis `tester_adaptateur.py etat-civil <identifiant>` (réponse ou motif de refus, sans rien signer).
Preuve déjà faite sur 3 jeux fictifs (Excel en français jj/mm/aaaa, JSON imbriqué, CSV Windows-1252) :
`.venv\Scripts\python -m pytest tests\test_formats.py -v`.

## Demande en ligne de commande (vrai agent)

`.venv\Scripts\python scripts\demande.py --demarche concours-adjoints --usager BF-0001` : le script demande
l'identifiant, le mot de passe (caché) et le code TOTP d'un vrai agent, passe par le guichet (mêmes règles, même
journal) et affiche le résultat. Rien n'est enregistré. API pour les intégrateurs : `docs/API.md`.

## Banc de pannes automatique (avant la démo, PAS devant le jury)

1. `OUTILS_TEST=1` dans `.env`, puis `python scripts/outils_test.py` (crée 3 comptes de service de TEST,
   `outil-test-concours`, `outil-test-bourses`, `outil-test-curieux` : mêmes règles que les agents, aucune exemption).
2. `python scripts/banc_de_pannes.py` → une ligne ✅ / ❌ par vérification (registre coupé, lent, corrompu, rejeu,
   mauvaise finalité, attribut en plus, appels directs au registre, seuil non déclaré, agent curieux, consentement
   refusé / retiré / expiré, journal modifié, consultation cachée, réseau, double trace), en 45 s environ.
3. **Remettre `OUTILS_TEST=0`** puis `python scripts/outils_test.py` : les comptes de test sont supprimés.
4. `python scripts/remise_a_zero.py --oui` : journal et traces neufs, pour que l'historique des citoyens de la démo
   ne montre pas les lignes du banc. **Rien n'est effacé** : l'ancien journal et les traces des registres sont
   archivés (renommés avec la date) et l'archive reste vérifiable :
   `docker compose exec mediateur python /journal/verifier.py /donnees/mediateur-archive-<date>.sqlite3 --registres`
   (les écarts « ABSENTE du journal » qu'elle montre sont les appels directs du banc, scénario A : attendus).

## Après la démo

`python scripts/panne.py` (tout `normal`). Pour tout arrêter sans rien perdre : `docker compose stop`.
