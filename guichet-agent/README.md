# Couche « guichet agent »

**Rôle** : l'écran de l'agent d'administration (`https://guichet.griot.test`). FastAPI + Jinja2, rendu serveur,
aucun JavaScript.

## Ce qu'il fait

- Connexion Keycloak (realm `griot`) : **mot de passe + TOTP obligatoire**, rôle `agent-guichet`. Le service de
  l'agent vient de son groupe dans le jeton, jamais d'un formulaire.
- Choix de la démarche (seulement celles du catalogue **en vigueur** à la passerelle), identifiant de l'usager
  (champ vide, exemple grisé), envoi.
- Statut « en attente de l'usager » avec un bouton Actualiser.
- Résultat : « majeur : oui », nationalité, casier vierge… (seulement ce que la démarche demande), ou le motif de refus
  de chaque attribut. Depuis le 17/11 les registres ne signent plus (LIMITES.md) : la passerelle valide la réponse
  contre le contrat et ne remet que l'attribut calculé ; le guichet ne vérifie plus de signature.
- Refus : motif clair (« Registre indisponible, rien n'a été deviné », « finalité non autorisée »…).
- Page `/controle` pour le rôle `controleur` (comme un délégué à la protection des données) : alertes, état des
  registres, catalogue et son empreinte, bouton « Vérifier le journal ». **Lecture seule**.

## Ce qu'il appelle

Uniquement la **passerelle d'échange** (`passerelle/openapi.yaml`). Il n'est pas sur le réseau des registres :
il ne peut pas la contourner.

## Contrat

`openapi.yaml` (généré, vérifié par `tests/test_openapi.py`) : les pages et formulaires HTML du guichet.

## Tests

`tests/test_guichet.py` : gabarits sans script ni ressource externe, et (pile démarrée) pages protégées renvoyées vers la
connexion Keycloak. Le reste est testé de bout en bout contre la pile qui tourne
(`tests/e2e/e2e_jalon1.py`, banc de pannes `resilience/banc_de_pannes.py`) et par son contrat (`tests/test_openapi.py`).
