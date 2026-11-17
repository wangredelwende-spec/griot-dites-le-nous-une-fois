# Couche « guichet agent »

**Rôle** : l'écran de l'agent d'administration (`https://guichet.griot.test`). FastAPI + Jinja2, rendu serveur,
aucun JavaScript.

## Ce qu'il fait

- Connexion Keycloak (realm `griot`) : **mot de passe + TOTP obligatoire**, rôle `agent-guichet`. Le service de
  l'agent vient de son groupe dans le jeton, jamais d'un formulaire.
- Choix de la démarche (seulement celles du catalogue **en vigueur** à la passerelle), identifiant de l'usager
  (champ vide, exemple grisé), envoi.
- Statut « en attente de l'usager » avec un bouton Actualiser.
- Résultat : « majeur : oui — signé par le registre d'état civil, signature vérifiée, valable jusqu'à 14 h 13 »,
  avec l'empreinte courte de la clé du registre. Le guichet **revérifie lui-même** chaque signature avec la clé
  publique lue dans le volume du registre (lecture seule) : la passerelle ne peut ni la fournir ni la remplacer.
- Refus : motif clair (« Registre indisponible, rien n'a été deviné », « finalité non autorisée »…).
- Page `/controle` pour le rôle `controleur` (comme un délégué à la protection des données) : alertes, état des
  registres, catalogue et son empreinte, bouton « Vérifier le journal ». **Lecture seule**.

## Ce qu'il appelle

Uniquement la **passerelle d'échange** (`passerelle/openapi.yaml`). Il n'est pas sur le réseau des registres :
il ne peut pas la contourner.

## Contrat

`openapi.yaml` (généré, vérifié par `tests/test_openapi.py`) : les pages et formulaires HTML du guichet.

## Tests

Pas encore de tests unitaires : le guichet est testé de bout en bout contre la pile qui tourne
(`tests/e2e/e2e_jalon1.py`, banc de pannes `resilience/banc_de_pannes.py`) et par son contrat (`tests/test_openapi.py`).
