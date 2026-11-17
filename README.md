# Griot Secure : « Dites-le-nous une fois »

Passerelle d'interopérabilité libre (AGPL-3.0) : les pièces circulent entre administrations, pas les usagers.
Équipe Griot Secure (BIT), finale du Hackathon 226, sujet 02.

<!-- Présentation complète (concept, scénario d'Awa, installation, banc de pannes) : à rédiger par Enock. -->

## Les démarches dépendent des registres du contrat

Les trois démarches du catalogue actif (concours direct de la fonction publique, entreprise individuelle au CEFORE,
certificat de nationalité) sont **choisies en fonction des registres du contrat commun du jury** (état civil,
nationalité, casier judiciaire). Si le contrat change ce que ces registres savent répondre, on change de démarche
sans toucher au code :

| Pour changer… | On modifie seulement |
|---|---|
| une démarche (finalité, demandeur, attributs permis, durée de l'accord) | `consentement-minimisation/catalogue/demarches.yaml` |
| les noms de champs d'un registre | `consentement-minimisation/catalogue/correspondance.yaml` |

Le catalogue est relu à chaud et **validé** : une version invalide est refusée, l'ancienne reste en vigueur.
Les démarches retirées (passeport, bourse, majorité) sont conservées, inactives, dans `demarches-inactives.yaml`.
Limites connues et fonctions désactivées : `LIMITES.md`.
