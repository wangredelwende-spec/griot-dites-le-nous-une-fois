# Remarques pour Enock

Relu le 17/11/2026, d'après le code de `main` au commit `053d043`, mis à jour au commit `2e2b4e4`.
Les chemins cités ici sont ceux d'aujourd'hui : ils vont changer (un dossier par couche). Les chemins à jour seront
dans [OU_TROUVER_QUOI.md](OU_TROUVER_QUOI.md).

## 1. Tes fichiers : rien trouvé à relire

Il n'existe pas de branche `docs` sur GitHub : `origin` n'a que `main`. Et sur `main`, tous les commits viennent du
compte d'Esther. Je n'ai donc relu aucun texte de toi, et je n'ai réécrit aucun de tes fichiers.
**Si tu as des textes ailleurs (autre branche, autre dépôt, document partagé), envoie le lien** : je
relirai en suivant la liste du point 2.

## 2. Faits à jour, à vérifier dans tes textes (vidéo, Concept, scénario)

Si un de tes textes dit autre chose, c'est lui qui est dépassé, pas le code.

| Sujet | Ce que dit le code aujourd'hui | Où le voir |
|---|---|---|
| Scène principale | **Le passeport ordinaire**, et non plus le concours ni la bourse | `docs/test-manuel.md`, scène 1 |
| Service qui demande | **« Service des passeports – ONI »** (dans l'aperçu USSD : « L'ONI (passeports) ») ; agent de démo `moussa.kone` | `catalogue/annuaire.yaml` |
| Ce que reçoit l'ONI | **Deux réponses seulement** : « burkinabè » et « interdiction de sortie du territoire ». **Pas de « majeur »**, pas d'âge, et l'état civil n'est pas interrogé | `catalogue/demarches.yaml` |
| Mode du passeport | **Avec l'accord de l'usager** (consentement) : l'usager voit l'aperçu et confirme | idem |
| Qui décide du mode | **Chaque registre** dit, pour chaque service, s'il accepte le consentement, la base légale (avec quels textes), ou les deux. Un passeport passé en « base légale » est refusé | `adaptateurs/*.yaml` (bloc `bases`), `docs/AJOUTER_UNE_DEMARCHE.md` |
| Concours | Démarche secondaire : **base légale**, 3 registres en parallèle, âge **18 à 37 ans au 31/12/2026** | `docs/test-manuel.md`, scène 1 ter |
| Direction des concours | Elle dépend du **ministère des Serviteurs du peuple** (ancien ministère de la Fonction publique, renommé au remaniement du 12 janvier 2026) | `catalogue/annuaire.yaml` |
| Majorité | **18 ans** (avant : 20 ans), loi n°012-2025/ALT ; c'est un paramètre | démarche « Vérifier la majorité » |
| Écran de l'usager | **USSD `*226#`** à `https://usager.griot.test`, et **portail web** à `https://usager.griot.test/portail` (mêmes comptes, même journal) | `ussd_sim/`, `portail_usager/` |
| Présentation | **Par couche**, comme le demande le sujet : registres, passerelle d'échange, consentement et minimisation, journal de traçabilité, espace usager ; guichet et résilience en bonus | [ARCHITECTURE.md](ARCHITECTURE.md) |
| API des registres | **Rien de définitif** : le jury publiera un contrat OpenAPI commun aux 3 registres | — |
| Menu USSD | 1. Demandes en attente, 2. Qui a consulté mes données, 3. Retirer un accord, 4. Langue (seulement si une 2ᵉ langue est complète), 0. Quitter | `traduction-moore/phrases-ussd.csv` |
| Reçu | **16 caractères** en 4 groupes (« 9035 47b3 1c2e 9f04 ») | `journal/verifier.py` |
| Mooré | **Jamais proposé tant qu'il est incomplet**. Malkiram traduit dans `traduction-moore/A_TRADUIRE_MALKIRAM.xlsx` (branche `docs-claude`) | `docs/fiche-oral.md`, question 28 |
| « Scénario d'Awa » | Awa (`awa.ouedraogo`) est agente du **service des bourses**. La scène principale est maintenant le passeport : il faut peut-être changer de personnage. L'usagère du passeport dans la démo : Aminata Kaboré (`BF-0001`, téléphone `70000001`) | `docs/test-manuel.md` |

## 3. Dans `main` : passages dépassés (à signaler à Esther, pas à toi)

- `docs/test-manuel.md`, préparation : « 9 services « healthy » ». Depuis le portail web, il y en a **10**.

- `docs/REGLES_DU_SOCLE.md`, règle 3 : l'exemple dit « L'ONI recevra : majeur = oui ; burkinabè = oui ». Mais le
  passeport ne demande plus l'âge (voir `catalogue/demarches.yaml`).
- `FEUILLE_DE_ROUTE.md` (à la racine) ne contient que 2 points, alors que d'autres documents y renvoient ou en
  annoncent d'autres. Points déjà écrits ailleurs qui pourraient y entrer (aucun n'est nouveau) :
  - un jeton par registre (« échange de jeton »), au lieu du jeton émis pour le médiateur : `LIMITES.md` ;
  - une « ancre externe » du journal, pour les demandes refusées avant tout registre : `LIMITES.md` ;
  - une description signée publiée par chaque registre, au lieu de la lecture de ses fichiers YAML : `LIMITES.md` ;
  - la connexion des usagers par l'identifiant unique électronique : `LIMITES.md` ;
  - le médiateur ouvert aux seuls systèmes autorisés, avec TLS mutuel : `docs/API.md` ;
  - SD-JWT, X-Road, un vrai USSD, le consentement du représentant légal : `docs/fiche-oral.md`, question 39 ;
  - une version des textes mooré sans les lettres hors GSM (ɛ, ɩ, ʋ, tildes) pour un vrai réseau :
    `traduction-moore/A_RELIRE.md` (branche `docs-claude`).

## 4. Faits sur le Burkina écrits dans `main` sans source

Je ne les ai pas repris dans mes documents. Avant de les dire au jury, il faut une source :

- « ministère de la Sécurité » dans le nom du service des passeports (`catalogue/annuaire.yaml`, `keycloak/realm-griot.json`) ;
- « l'ONI enrôle la CNIB, donc connaît déjà la date de naissance » : c'est la raison pour laquelle le passeport
  ne demande pas l'âge (`catalogue/demarches.yaml`, `adaptateurs/etat-civil.yaml`, `docs/fiche-oral.md` question 23 bis,
  `docs/test-manuel.md`) ;
- « copies légalisées » dans le dossier papier (`docs/test-manuel.md`, `docs/fiche-oral.md`, `docs/API.md`) ;
- les noms des opérateurs pour l'USSD (`docs/fiche-oral.md`, question 13) ;
- l'existence et l'adresse d'« e-concours » (`docs/API.md`, `docs/fiche-oral.md` question 21) et d'un « e-casier »
  (`docs/fiche-oral.md` question 14) ;
- la loi n°081-2015/CNT et le communiqué du concours (18 à 37 ans) : `catalogue/demarches.yaml`. Le catalogue dit
  lui-même « référence exacte du communiqué à compléter par l'équipe ».

## 5. Sources vérifiées (les seules utilisées dans mes documents)

| Fait | Source |
|---|---|
| Loi n°001-2021/AN (données personnelles) : consentement « exprès, libre, spécifique et éclairé » ; données « adéquates, pertinentes et non excessives » | <https://assembleenationale.bf/storage/Loi/kDsWHXOTUCQFVESChh8BlBdiZnCrdTsOpXe1rzmH.pdf> |
| Majorité civile à 18 ans (avant : 20 ans), loi n°012-2025/ALT | <https://burkina24.com/?p=418360> |
| Passeport AES en circulation depuis le 29 janvier 2025, produit par l'ONI | <https://www.sidwaya.info/retro-2025-carte-et-passeport-aes-larsenal-identitaire-de-lespace-sahelien-operationnel/>, <https://www.sidwaya.info/?p=148180> |
| Dossier passeport du communiqué de 2017 (acte de naissance, certificat de nationalité, CNIB, casier) : c'est **le dossier classique**, pas forcément la règle actuelle | <https://www.wakatsera.com/burkina-faso-les-conditions-dobtention-dun-passeport-ordinaire/> |
| Ministère de la Fonction publique devenu ministère des Serviteurs du peuple (remaniement du 12 janvier 2026) | <https://fr.allafrica.com/stories/202601130078.html> |
