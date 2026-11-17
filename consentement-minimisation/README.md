# Couche « consentement et minimisation »

**Rôle** : ne transmettre que l'utile, et seulement avec l'accord de l'usager quand la démarche l'exige.
« Vous voyez avant » : l'usager voit exactement ce qui partira, puis confirme ou refuse.

## Ce que contient la couche

| Dossier | Ce qu'il fait | Où il s'exécute |
|---|---|---|
| `catalogue/` | `demarches.yaml` (démarche → service, finalité, base « consentement » ou « base_legale », attributs et paramètres) et `annuaire.yaml` (services, registres, format de l'identifiant) | lu par la passerelle et le guichet (lecture seule) |
| `consentement/catalogue.py` | charge et **valide** le catalogue ; un catalogue invalide est refusé avec ses raisons, l'ancien reste en vigueur | processus de la passerelle |
| `consentement/usager.py` | routes de l'usager : demandes en attente avec **aperçu**, confirmer, refuser, liste des accords, **retirer** un accord, langues ; **expiration** après 10 minutes | processus de la passerelle |
| `catalogue/attributs.yaml` | attributs **permis** (majeur, nationalite_bf, casier_vierge, identite, naissance_filiation) : registre, règle, champs logiques, services autorisés | passerelle |
| `catalogue/correspondance.yaml` | nom logique → nom du champ dans le **contrat** des registres (seul endroit à changer avec le contrat) | passerelle |
| `regles_attributs/` | **calcul de l'attribut minimal** (âge entre deux seuils, égalité, nombre nul, cases précises) ; `minimisation.py` : depuis la fiche brute du registre | processus de la passerelle |

Depuis le 17/11, le calcul tourne dans la **passerelle** : les registres suivent le contrat et renvoient la fiche ;
la passerelle la valide, en tire l'attribut permis (« majeur : oui ») et ne laisse sortir que lui. Accord par
démarche : durée `duree_accord_heures`, retirable ; tant qu'il est valable, la réponse est immédiate.

## Contrat

`openapi.yaml` (généré depuis le code par `scripts/generer_openapi.py`, vérifié par `tests/test_openapi.py`) :

| Route | Rôle |
|---|---|
| `GET /usagers/{sujet_ref}/en-attente` | aperçu exact : « Le service des bourses recevra : majeur = oui. Rien d'autre. » |
| `POST /demandes/{id}/confirmer` | une confirmation pour tout l'aperçu ; renvoie l'empreinte de la ligne du journal (reçu) |
| `POST /demandes/{id}/refuser` | rien n'est transmis |
| `GET /usagers/{sujet_ref}/accords` | accords donnés, retirables |
| `POST /demandes/{id}/retirer` | avant la remise : rien ne part ; après : le retrait est écrit au journal |
| `GET /catalogue/langues` | langues dans lesquelles toutes les finalités sont traduites |

Chaque appel porte l'en-tête `X-Cle-Canal` (un secret par écran : USSD ou web). Détails et exemples :
`docs/API_USAGER.md`.

## Règles appliquées

- Une démarche ne peut demander que les attributs écrits dans le catalogue (rien « en plus »).
- Sans réponse de l'usager en 10 minutes : les réponses en attente sont effacées, rien ne part.
- Le journal consigne le fait (« confirmation », « retrait »), jamais la valeur.

## Tests

`consentement-minimisation/tests/` : catalogue (validation, rechargement, démarche refusée), langues,
preuve de minimisation. Lancer depuis la racine : `.venv\Scripts\python -m pytest consentement-minimisation\tests`.
