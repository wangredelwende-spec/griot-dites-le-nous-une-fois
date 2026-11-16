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
  `nationalite_burkinabe` et `casier_judiciaire_vierge`.
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

## 3. La double clé

Le catalogue ne suffit pas : **chaque registre décide lui-même** quels services peuvent lui demander quel attribut
(liste `services:` de l'attribut, dans `adaptateurs/<registre>.yaml`).
Si la mairie ajoute une démarche qui demande le casier, le médiateur la laisse passer, mais affiche un avertissement
au démarrage (`docker compose logs mediateur`). Le registre du casier refuse alors lui-même, avec une réponse signée :
« service non autorisé par le registre à demander cet attribut ».

Pour autoriser un nouveau service, il faut donc l'accord des deux côtés : le catalogue (le médiateur)
**et** l'adaptateur du registre (l'administration qui détient la donnée).
