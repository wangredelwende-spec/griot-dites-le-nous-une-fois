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

## Repli : le casier du jury n'a pas de colonne « peines complémentaires »

La démarche Passeport demande normalement l'attribut `interdiction_sortie_territoire` (le plus minimal : le
service des passeports n'a pas à savoir si le casier est vierge). Si le casier du jury n'a **pas** de colonne
« peines complémentaires », cet attribut ne peut plus être calculé : on bascule la démarche sur
« casier judiciaire vierge » en changeant **UNE SEULE LIGNE** du catalogue, sans toucher au code.

Dans `catalogue\demarches.yaml`, démarche `passeport-ordinaire`, remplacer la ligne :

```yaml
      - {attribut: interdiction_sortie_territoire, libelle: interdiction de sortie du territoire, attendu: false}
```

par la ligne « repli » donnée en commentaire juste en dessous :

```yaml
      - {attribut: casier_judiciaire_vierge, libelle: casier judiciaire vierge, si_non: "casier non vierge : dossier à instruire"}
```

Puis `docker compose restart mediateur guichet`. Rien d'autre :

- le registre casier **autorise déjà** le service passeport sur « casier vierge » (double clé déclarée dans
  `adaptateurs\casier.yaml` — c'est le seul autre service autorisé avec la Direction des concours) ;
- l'aperçu USSD suit tout seul : il est fabriqué depuis le catalogue (« … recevra : casier judiciaire
  vierge = oui/non. Rien d'autre. », moins de 160 caractères), jamais en dur ;
- si l'adaptateur casier du jury ne déclare plus `interdiction_sortie_territoire` (colonne absente), la ligne
  d'origine ferait refuser le démarrage du médiateur (« attribut inconnu ») : la bascule est obligatoire.

**Plus large, donc à ne faire que si la colonne manque** : avec le repli, le service des passeports apprend
qu'une personne a été condamnée (casier non vierge) même sans interdiction de sortie. Revenir à l'attribut
normal dès que la colonne existe. Testé : les deux réglages passent la suite (`tests\test_catalogue.py`).

## API du jury : réseau

Les registres sont sur des réseaux Docker **sans Internet**. Si l'API du jury est sur le réseau local, le registre
ne peut pas la joindre tel quel : voir `A_TRANCHER_DONNEES_JURY.md` (décision d'Esther avant de l'ouvrir).
