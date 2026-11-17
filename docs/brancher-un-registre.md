# Brancher le registre d'une autre équipe

Il n'y a pas de contrat commun imposé : chaque équipe définit ses registres. Le nôtre est
`registres/contrat/contrat-registres.yaml`. Brancher le registre d'une **autre** équipe (autre adresse, autres routes,
autres noms de champs) ne touche **aucun code** : deux fichiers de `consentement-minimisation/catalogue/` à modifier,
plus le contrat OpenAPI publié par cette équipe, copié tel quel. La passerelle les relit **à chaud**, sans redémarrer.

## Ce qu'il faut demander à l'autre équipe

1. L'**adresse** de son registre (ex. `http://10.0.0.42:7000`).
2. Son **contrat OpenAPI** (fichier YAML ou JSON) : la route qui lit une personne par son identifiant, avec **un seul**
   paramètre (`/api/v2/personnes/{numero}`), le schéma de la réponse 200, et 404 si la personne est inconnue.
3. Le **sens** de ses champs : lequel est la date de naissance, la date de décès, etc. (on ne devine pas).

## Les 3 gestes (exemple : leur état civil remplace le nôtre)

**1. Copier leur contrat**, sans le modifier, dans `consentement-minimisation/catalogue/contrats/autre-equipe.yaml`.

**2. `annuaire.yaml`**, bloc du registre (ici `etat-civil`) :

```yaml
  etat-civil:
    url: http://10.0.0.42:7000               # leur adresse
    chemin: /api/v2/personnes/{numero}       # leur route, recopiée MOT POUR MOT de leur contrat
    nom: registre d'état civil
    contrat: contrats/autre-equipe.yaml      # leurs réponses sont jugées sur LEUR contrat
```

Facultatif : `en_tete_cle` + `cle_secret` si leur registre exige une clé API (nom de l'en-tête, fichier dans
`/run/secrets`).

**3. `correspondance.yaml`**, même bloc : à gauche nos noms logiques (ne pas changer), à droite **leurs** noms de champs.

```yaml
  etat-civil:
    nom: nom_famille
    prenoms: prenom
    date_naissance: ne_le
    lieu_naissance: ne_a
    pere: pere_nom
    mere: mere_nom
    date_deces: decede_le
```

Un champ qu'ils n'ont pas : laisser vide (`null`). L'attribut qui en dépend sera **refusé**, jamais deviné.

## Ce que la passerelle vérifie toute seule

| Situation | Résultat |
|---|---|
| Route absente de leur contrat, ou plus d'un paramètre | **catalogue refusé**, l'ancien reste en vigueur, raison au journal |
| Contrat illisible | idem |
| Réponse qui ne respecte pas leur contrat | rejetée, ligne d'alerte « réponse corrompue : non conforme au contrat » |
| 404 | « citoyen inconnu » |
| Pas de réponse en 2 s (+ 1 réessai) | « registre indisponible, rien n'a été deviné » |
| Champ de la correspondance vide ou absent de la fiche | refus « réponse impossible » |

La fiche brute de leur registre ne sort jamais de la passerelle : seul l'attribut calculé (« majeur : oui ») part.

## Essai à blanc chronométré (sans Docker, le dépôt n'est pas modifié)

```powershell
.venv\Scripts\python scripts\essai_a_blanc_autre_equipe.py
```

Le script démarre un **faux registre « autre équipe »** (`scripts/autre_equipe/` : route `/api/v2/personnes/{numero}`,
champs `ne_le`, `decede_le`…, son propre contrat), copie le catalogue dans un dossier temporaire, démarre la vraie
passerelle sur cette copie et **lance le chrono**. Faire les 3 gestes ci-dessus dans le dossier affiché
(adresse `http://127.0.0.1:7000`, contrat : `scripts\autre_equipe\contrat-autre-equipe.yaml`), puis Entrée.
Le script joue le concours direct (BF-0001 majeure, BF-0003 mineure, BF-0009 décédée, BF-9999 inconnu, réponse
hors contrat, journal intègre), affiche ✅ / ❌ ligne par ligne et le **temps total**. Objectif : moins de 5 minutes.
`--auto` fait les modifications à la place de l'humain (test automatique : `passerelle/tests/test_epreuve.py`).

## Sur la pile Docker

Mêmes 3 gestes dans `consentement-minimisation/catalogue/` (monté en lecture seule dans la passerelle, relu à chaud).
**Limite réseau** : le réseau `registres` de la passerelle n'a pas de sortie (`internal: true`). Pour joindre un
registre sur une autre machine, il faut soit lancer leur conteneur sur notre réseau `registres`, soit un relais à
destination unique (comme `relais-api-jury`). C'est un choix réseau dans `docker-compose.yml`, pas un changement de code.

## Limites

- Leur fiche doit être un objet JSON « à plat » (un champ = une valeur) ; un champ imbriqué demanderait du code.
- L'identifiant doit être dans la route (`{numero}`), pas dans un paramètre de requête (`?numero=`).
- Le même identifiant de citoyen est supposé valable chez eux et chez nous.
