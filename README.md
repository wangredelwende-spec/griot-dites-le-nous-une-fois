# Griot Secure : « Dites-le-nous une fois »

Passerelle d'interopérabilité libre (AGPL-3.0) : les pièces circulent entre administrations, pas les usagers.
Équipe Griot Secure (BIT), finale du Hackathon 226, sujet 02.

<!-- Présentation complète (concept, scénario d'Awa, installation, banc de pannes) : à rédiger par Enock. -->

## Les démarches dépendent des registres du contrat

Les trois démarches du catalogue actif (concours direct de la fonction publique, entreprise individuelle au CEFORE,
certificat de nationalité) sont **choisies en fonction des registres du contrat commun du jury** (état civil,
nationalité, casier judiciaire). Si le contrat change ce que ces registres savent répondre, on change de démarche
sans toucher au code : `consentement-minimisation/catalogue/demarches.yaml` (et `attributs.yaml` si un nouvel
attribut est nécessaire). Le catalogue est relu à chaud et **validé** : une version invalide est refusée, l'ancienne
reste en vigueur. Démarches retirées : `demarches-inactives.yaml`. Limites et fonctions désactivées : `LIMITES.md`.

## Remplacer le contrat (celui du jury, ou celui d'une autre équipe)

**Contrat actuel : PROVISOIRE** (`registres/contrat/contrat-provisoire.yaml`, citoyens : `registres/donnees/citoyens-provisoires.yaml`).
Les réponses des registres sont validées contre le contrat : une réponse non conforme est rejetée et écrite au journal.
Pour brancher le contrat du jury, **deux fichiers** (plus la liste des citoyens) :

1. le **contrat** OpenAPI : le fichier désigné par `GRIOT_CONTRAT` (Docker : `CONTRAT_REGISTRES` dans `.env`) ;
2. `consentement-minimisation/catalogue/correspondance.yaml` : pour chaque nom logique (`date_naissance`, `nationalite`…),
   le nom du champ dans le contrat. Une valeur vide = refus (on ne devine pas) ;
3. la **liste des citoyens** (`GRIOT_CITOYENS`, Docker : `CITOYENS_REGISTRES`), pour les registres simulés et les tests.

Puis, si l'adresse ou la route d'un registre change : `registres:` dans `consentement-minimisation/catalogue/annuaire.yaml`
(`url`, `chemin`, éventuellement une clé API de registre). Brancher le registre d'une autre équipe = ce seul bloc.
Enfin : `.venv\Scripts\python -m pytest` (les tests lisent ces fichiers ; un nom de champ oublié dans
`correspondance.yaml` fait échouer `test_correspondance_du_depot_couvre_le_contrat_et_les_attributs`).
Avec un contrat ou une liste hors du dépôt : `$env:GRIOT_CONTRAT="…"; $env:GRIOT_CITOYENS="…"; .venv\Scripts\python -m pytest`.

## Voir le portail sans Docker

`.venv\Scripts\python scripts\demo_locale.py` puis http://127.0.0.1:8081/portail (numéro `70000001`, PIN `1234`) et
http://127.0.0.1:8082/ (simulateur `*226#`). Registres simulés, données fictives.
