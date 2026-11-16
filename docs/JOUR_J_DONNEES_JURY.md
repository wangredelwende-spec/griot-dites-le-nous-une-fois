# Jour J : brancher les données du jury (configuration seulement, aucun code)

Toutes les commandes : PowerShell, dans le dossier du dépôt. Les données du jury restent dans `donnees_jury/`
(ignoré par git : **jamais commitées**).

## Formats acceptés (réglés dans `adaptateurs/<registre>.yaml`)

| Format | `source:` | Réglages |
|---|---|---|
| CSV | `type: csv` | `separateur: auto` (; ou ,), `encodage: auto` (UTF-8, sinon Windows-1252) |
| Excel .xlsx | `type: xlsx` | `feuille:` (sinon la première) ; 1re ligne = noms des colonnes ; dates Excel lues |
| JSON | `type: json` | `liste: registre.personnes` (où est la liste) ; champs imbriqués : `naissance.date` |
| SQLite | `type: sqlite` | `table:` ou `requete: SELECT …` (lecture seule) |
| Dump SQL | `type: sql` | rejoué dans une base SQLite en mémoire ; `table:` ou `requete:` |
| PDF texte | `type: pdf` | tableaux lus avec pdfplumber ; 1re ligne = noms des colonnes |
| PDF scanné | (aucun) | converti **une fois** en CSV par le conteneur OCR (étape 3 bis), puis `type: csv` |
| API HTTP | `type: api` | `url: "http://…?nip={sujet_ref}"`, `liste:`, `delai: 2`, `entetes: {Authorization: "Bearer {secret:api_jury}"}` |

Et aussi, pour tous les formats : `identite:` (colonne qui identifie la personne), `champs:` (noms des colonnes),
`format_date: "%d/%m/%Y"` (ou une liste de formats), `correspondances:` (« Burkinabè », « BF », « burkinabe »…
→ oui ; valeur inconnue → refus). « vers 1990 », case vide, valeur non reconnue : **refus « donnée insuffisante »**.

## Procédure (environ 30 minutes)

**1. Copier** les fichiers du jury dans `donnees_jury\` (ne rien renommer : garder les originaux intacts).

**2. Inspecter** (rien n'est modifié) :
```powershell
.venv\Scripts\python scripts\inspecter_donnees.py donnees_jury\<fichier1> donnees_jury\<fichier2> donnees_jury\<fichier3>
```
Lire : colonnes, formats de date, cases vides, valeurs distinctes (nationalité), identifiant probable, doublons,
homonymes, **identifiant commun entre les fichiers**. S'il n'y a pas d'identifiant commun : **STOP**, en parler à
Esther avant tout (rapprochement à décider, voir `A_TRANCHER_DONNEES_JURY.md`).

**3. Générer les brouillons d'adaptateur** :
```powershell
.venv\Scripts\python scripts\inspecter_donnees.py donnees_jury\<fichier1> donnees_jury\<fichier2> donnees_jury\<fichier3> --proposer-yaml
```
→ `donnees_jury\brouillons\<registre>-<fichier>.yaml`. Les relire : chercher « À VÉRIFIER », vérifier
`identite`, `champs`, `format_date` et **chaque valeur** de `correspondances` (oui / non). Les groupes, attributs
et la double clé sont repris de l'adaptateur actuel : ne pas y toucher.

**3 bis. PDF scanné seulement** (le conteneur OCR n'a aucun réseau) :
```powershell
docker compose --profile ocr run --rm ocr /donnees/<fichier>.pdf
```
→ `<fichier>.csv` + `<fichier>.provenance.json` (empreintes SHA-256 de l'original et du CSV). Toute case douteuse
reste VIDE (donc refus). Relire le CSV, puis reprendre l'étape 2 sur ce CSV. Option `--seuil 80` (confiance
minimale d'un mot, 0-100).

**4. Tester chaque brouillon** sur des personnes du jury, sans rien signer ni journaliser :
```powershell
.venv\Scripts\python scripts\tester_adaptateur.py etat-civil <identifiant> --yaml donnees_jury\brouillons\<brouillon>.yaml --donnees donnees_jury
```
Essayer au moins : une personne ordinaire, un mineur, une date incomplète, un homonyme, un décès, un casier non
vierge. Chaque refus affiche son motif précis (qui, en vrai, ne sort jamais du registre).

**5. Mettre en service** :
- copier chaque brouillon validé dans `adaptateurs\<registre>.yaml` ;
- dans `.env` : `DONNEES_REGISTRES=./donnees_jury` (et `API_JURY_SECRET=…` si le jury donne une API) ;
- redémarrer **seulement les registres** (prévenir l'équipe) :
```powershell
docker compose up -d --force-recreate --wait registre-etat-civil registre-nationalite registre-casier
docker compose logs registre-etat-civil registre-nationalite registre-casier | Select-String "source"
```
Chaque registre écrit : format, nombre de lignes et **empreinte SHA-256** du fichier lu. Un YAML ou un fichier
illisible : le registre refuse de démarrer, avec le motif (`docker compose logs registre-…`).

**6. Vérifier** : `python scripts\remise_a_zero.py --oui` (journal neuf), puis le banc de pannes en mode test
(`docs/test-manuel.md`, « Banc de pannes automatique ») → 18/18 attendu, puis une démarche Passeport au guichet
sur une personne du jury.

**Revenir aux données fictives** : `DONNEES_REGISTRES=./registres_sim/donnees_fictives` dans `.env`,
`git checkout adaptateurs\`, puis l'étape 5.

## API du jury : réseau

Les registres sont sur des réseaux Docker **sans Internet**. Si l'API du jury est sur le réseau local, le registre
ne peut pas la joindre tel quel : voir `A_TRANCHER_DONNEES_JURY.md` (décision d'Esther avant de l'ouvrir).
