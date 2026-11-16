# Feuille de route (faits bruts, à compléter en phase 3)

<!-- Texte à rédiger par Enock. Ci-dessous : les points déjà décidés, notés au fil de la finale. -->

## Gouvernance du catalogue

- Aujourd'hui : le catalogue des démarches (`catalogue/demarches.yaml`) et les autorisations des registres
  (`adaptateurs/*.yaml`) se modifient **uniquement par fichier YAML**, validé au démarrage du médiateur ;
  l'empreinte SHA-256 du catalogue est écrite au journal à chaque chargement.
- Le contrôle (rôle `controleur`, page `/controle` du guichet) est en **lecture seule**.
- À faire : un écran d'administration du catalogue avec **validation à deux personnes** (une propose, une autre
  approuve), chaque changement écrit au journal chaîné.

## Consentement des mineurs

- Hors du prototype : consentement donné par le **représentant légal** pour un usager mineur.
