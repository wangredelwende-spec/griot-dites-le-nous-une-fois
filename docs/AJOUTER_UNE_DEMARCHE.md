# Ajouter une démarche en 2 minutes, sans toucher au code

Scène de démonstration « Adapter » : une administration ajoute une démarche en éditant **un fichier YAML**.

## 1. Écrire la démarche (1 minute)

Ajouter un bloc à la fin de `catalogue/demarches.yaml`, par exemple :

```yaml
  inscription-universite:
    libelle: Inscription à l'université (bourse d'études)
    services: [service-bourses]
    finalite: vérification des conditions de la bourse d'études
    base: consentement                  # l'usager verra l'aperçu et confirmera sur *226#
    attributs:
      - attribut: age_entre
        parametres: {min: 17, max: 25, date_reference: "2026-10-01"}
        libelle: âge de 17 à 25 ans au 01/10/2026
      - attribut: nationalite_burkinabe
        libelle: nationalité burkinabè
```

À retenir :
- `base: base_legale` exige `texte:`, c'est-à-dire le texte qui autorise la consultation sans accord.
- Les attributs possibles sont ceux que **les registres déclarent** dans `adaptateurs/<registre>.yaml` :
  `age_entre` (paramètres `min`, `max` facultatif, `date_reference` : une date ou `aujourd'hui`),
  `nationalite_burkinabe`, `casier_judiciaire_vierge` et `interdiction_sortie_territoire`.
- Facultatif, pour le guichet : `attendu: false` quand la bonne réponse est « non » (interdiction de sortie du
  territoire), et `si_non:` pour le texte montré quand la réponse est « non » (repli casier du passeport : « casier
  non vierge : dossier à instruire »). Une réponse « non » n'est jamais un refus : c'est une réponse signée.
- On ne peut pas demander « la date de naissance » : aucun registre ne la déclare.

## 2. Recharger (30 secondes)

```powershell
docker compose restart mediateur guichet
docker compose logs mediateur --tail 5
```

- Si le catalogue est **incomplet** (finalité, base ou texte manquant, attribut inconnu, paramètres faux), le médiateur
  **refuse de démarrer** et liste chaque erreur. Exemple : `démarche « inscription-universite » : base légale sans texte cité`.
- Sinon, la démarche apparaît au guichet des agents du service. L'**empreinte SHA-256** du nouveau catalogue est écrite
  dans le journal chaîné : on peut prouver quelles règles étaient en vigueur lors de chaque consultation.

## 3. La double clé : l'accord du registre

Le catalogue ne suffit pas : **chaque registre décide lui-même**, dans `adaptateurs/<registre>.yaml`,
quels services peuvent lui demander quel attribut, **et avec quels paramètres**. Pour l'exemple ci-dessus,
l'état civil doit ajouter les seuils du service des bourses :

```yaml
# adaptateurs/etat-civil.yaml, attribut age_entre
    services:
      service-bourses:
        - {min: 18, date_reference: aujourd'hui}
        - {min: 17, max: 25, date_reference: "2026-10-01"}    # bourse d'études (ajout)
```

puis `docker compose restart registre-etat-civil`.

Sans cet ajout, le médiateur affiche un avertissement au démarrage (`docker compose logs mediateur`) et le
registre **refuse lui-même**, par une réponse signée : « paramètres non autorisés par le registre pour ce service »
(ou « service non autorisé par le registre à demander cet attribut »). Pourquoi les paramètres ? Sans cette règle,
un service pourrait poser « 25 ans ? 26 ans ? 27 ans ?… » et reconstituer la date de naissance.

Le registre vérifie aussi **lui-même** qui demande : le médiateur lui transmet le jeton Keycloak de l'agent, et le
registre en contrôle la signature (clés publiques de Keycloak), l'expiration et le groupe (= le service).
Un médiateur compromis ne peut donc pas se faire passer pour un autre service.

Pour autoriser un nouveau service, il faut l'accord des deux côtés : le catalogue (le médiateur)
**et** l'adaptateur du registre (l'administration qui détient la donnée). Chaque registre ne monte que SON
adaptateur ; le médiateur et le guichet les lisent en lecture seule et ne peuvent pas les modifier.
