# Couche « registres » (état civil, nationalité, casier)

**Rôle** : détenir la donnée et ne répondre que l'attribut demandé, **signé**. Un seul code, trois instances
(`registre-etat-civil`, `registre-nationalite`, `registre-casier`), choisies par la variable `ADAPTATEUR`.

## Une demande, côté registre

1. Vérifie **lui-même** le jeton Keycloak de l'agent (signature, expiration, groupe = service).
2. Double clé : l'attribut, la base (consentement ou texte de loi cité) et les paramètres (seuils d'âge, date de
   référence) doivent être déclarés pour ce service dans **son** adaptateur. Sinon : refus signé.
3. Retrouve la fiche (`app/adaptateur.py`) : 0 fiche → « introuvable », plusieurs → « identité ambiguë », personne
   décédée → refus.
4. Calcule l'attribut minimal avec `regles_attributs/` (couche consentement et minimisation, copiée dans son
   image) : la fiche ne sort jamais du conteneur.
5. Signe la réponse (JWT EdDSA / Ed25519, 10 minutes) avec **sa** clé privée. Les refus sont signés aussi, avec
   un motif public générique. Seul « indisponible » n'est pas signé.
6. Note la réponse dans sa **double trace** (numéro de demande, jti, date ; jamais la valeur).

## Ce que contient la couche

| Élément | Rôle |
|---|---|
| `adaptateurs/<registre>.yaml` | source, clé d'identité, champs, attributs et leur règle, services autorisés : brancher un registre = écrire ce fichier |
| `app/sources.py` | lecture CSV, Excel, JSON, SQLite, dump SQL, PDF, API HTTP |
| `app/main.py` | API, signature, interrupteur de panne (normal, lent, corrompu), double trace |
| `donnees_fictives/` | une vingtaine de citoyens fictifs (mineur, « né vers », homonymes, décédé, casier non vierge) |
| `import/ocr/` | conversion unique d'un PDF scanné en CSV, sans réseau |

## Contrat

`openapi.yaml` (généré, vérifié par `tests/test_openapi.py`) : `POST /attributs` (appelé par la passerelle
seulement, réseau `registres`) et `GET /trace` (double trace signée). Brancher un registre : `docs/JOUR_J_DONNEES_JURY.md`.

## Tests

`registres/tests/` : adaptateur (âges, dates incomplètes, homonymes, décès), formats de fichiers
(`donnees_formats/`, `adaptateurs_formats/`), API du registre (jeton, double clé, signature).
`.venv\Scripts\python -m pytest registres\tests`.
