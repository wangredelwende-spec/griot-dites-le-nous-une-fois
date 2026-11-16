# API du médiateur pour les intégrateurs (côté administration)

Pour brancher une **autre application d'administration** (logiciel métier d'un service, autre guichet) sur le
médiateur. L'API côté usager (USSD, portail) est décrite dans [API_USAGER.md](API_USAGER.md).

## Accès

- Adresse : `http://mediateur:8000`, **réseau Docker interne seulement** : le médiateur n'est jamais publié par
  Caddy. L'application intégrée tourne donc sur le réseau interne de l'administration, comme le guichet.
- **Chaque appel porte le jeton d'accès Keycloak d'un vrai agent** : `Authorization: Bearer <jeton>`.
  Pas de compte technique « qui peut tout » : on sait toujours quel agent a demandé quoi.
- Pour essayer sans rien développer : `scripts/demande.py` (même parcours que le guichet, saisie au clavier).

### Obtenir le jeton d'un agent

1. Déclarer l'application dans Keycloak (realm `griot`) comme client OIDC **confidentiel**, flux « authorization
   code » + PKCE, avec les mêmes trois « mappers » que le client `guichet` (`keycloak/realm-griot.json`) :
   `roles` (rôles du realm), `groupes` (groupes de l'agent = son service), `audience-mediateur` (audience
   `mediateur`).
2. L'agent se connecte dans son navigateur : **mot de passe + code TOTP** (obligatoires pour tous les comptes).
3. L'application reçoit le jeton d'accès et l'envoie au médiateur. Elle ne le stocke pas sur disque.

Le médiateur vérifie : signature (clés publiques de Keycloak), émetteur `https://auth.griot.test/realms/griot`,
audience `mediateur`, expiration, rôle `agent-guichet`, **un seul groupe de service** (le service vient du jeton,
jamais du corps de la demande). Le jeton est ensuite transmis tel quel à chaque registre, qui le **revérifie
lui-même** (double clé).

## 1. Faire une demande

`POST /demandes`

```json
{"id_demande": "6f1c2a4e-8b3d-4e5f-9a7b-1c2d3e4f5a6b",
 "demarche": "concours-adjoints",
 "sujet_ref": "BF-0001",
 "finalite": "vérification des conditions d'inscription au concours direct des adjoints administratifs"}
```

| Champ | Règle |
|---|---|
| `id_demande` | UUID v4 créé par l'application. **Le même identifiant renvoie le même résultat** sans rappeler les registres (rejeu). Réutilisé pour une autre demande : `409`. |
| `demarche` | Code d'une démarche de `catalogue/demarches.yaml` ouverte au service de l'agent. |
| `sujet_ref` | Identifiant de l'usager : lettres, chiffres, tirets (1 à 64). |
| `finalite` | **Exactement** celle du catalogue, sinon refus « finalité non autorisée ». |
| `attributs` | Facultatif. S'il est présent, ce doit être exactement la liste du catalogue (sinon refus). |

Aucun autre champ n'est accepté (`422`) : on ne peut rien demander « en plus ».

Réponse `200` (base légale : remise immédiate) :

```json
{"id_demande": "6f1c2a4e-…", "statut": "remise", "motif": "", "demarche": "concours-adjoints",
 "volets": [
   {"attribut": "age_entre", "registre": "etat-civil", "statut": "ok", "motif": "", "jeton": "eyJhbGciOiJFZERTQSJ9…"},
   {"attribut": "nationalite_burkinabe", "registre": "nationalite", "statut": "ok", "motif": "", "jeton": "eyJ…"},
   {"attribut": "casier_judiciaire_vierge", "registre": "casier", "statut": "indisponible",
    "motif": "Registre … indisponible (délai dépassé (3 s)), rien n'a été deviné"}]}
```

- **Le médiateur ne donne jamais la valeur en clair** : elle est dans `jeton`, la réponse **signée par le
  registre**. L'application doit la vérifier elle-même (voir 3).
- Statut de la demande : `remise`, `en_attente` (consentement : l'usager doit confirmer, avec `expire_le`),
  `confirmee`, `refuse`, `indisponible`, `expiree`, `retiree`, `retiree_apres_remise`, `bloquee` (limite de débit).
- Statut d'un volet : `ok` (avec `jeton`), `en_attente`, `remise` (déjà remis : jeton plus disponible),
  `non_transmis`, `refuse` (refus signé par le registre : `jeton` présent, sans valeur), `indisponible`.
- **Un volet indisponible ne donne jamais de « oui » global** : résultat incomplet, rien n'a été deviné.

## 2. Suivre une demande (consentement)

`GET /demandes/{id_demande}` : même forme de réponse. Seul l'agent qui a fait la demande peut la suivre (sinon
`404`). Dès que l'usager a confirmé, ce GET **remet** les réponses signées, **une seule fois** ; le médiateur
les efface ensuite.

## 3. Vérifier une réponse signée

JWT `EdDSA` (Ed25519), clé publique du registre : `/publiques/<registre>/cle.pem` (volume du registre, en
lecture seule). Vérifier : signature, `iss` = `registre-<registre>`, `aud` = code du service de l'agent, `exp`,
`demande` = `id_demande`, `sub` = `sujet_ref`, `jti` jamais vu, et la forme exacte des claims. Un seul écart :
refuser. Exemple de contenu :

```json
{"iss": "registre-etat-civil", "aud": "direction-concours", "sub": "BF-0001", "demande": "6f1c2a4e-…",
 "statut": "ok", "age_equal_or_over": {"18": true, "38": false}, "date_reference": "2026-12-31",
 "iat": 1794846581, "exp": 1794847181, "jti": "…"}
```

## 4. Erreurs

| Code | Cas |
|---|---|
| `401` | Jeton absent, invalide ou expiré : reconnecter l'agent. |
| `403` | Pas le rôle `agent-guichet` ; compte de test alors que `OUTILS_TEST=0`. |
| `404` | Demande inconnue ou faite par un autre agent. |
| `409` | `id_demande` déjà utilisé pour une autre demande. |
| `422` | Corps mal formé ou champ en trop. |
| `503` | Keycloak injoignable : impossible de vérifier l'agent, donc refus. |

Les refus métier (finalité, démarche non ouverte au service, limite de débit) répondent `200` avec
`statut: refuse` ou `bloquee` et un `motif` lisible : ils sont écrits au journal.

## 5. Exemples PowerShell

À lancer depuis une machine du réseau interne. `$jeton` est le jeton d'accès obtenu par l'application lors de la
connexion de l'agent (étape « Obtenir le jeton »).

```powershell
$MEDIATEUR = "http://mediateur:8000"
$entetes = @{ Authorization = "Bearer $jeton" }

# 1. Demande (le corps est envoyé en UTF-8 : la finalité contient des accents)
$corps = @{
  id_demande = [guid]::NewGuid().ToString()
  demarche   = "concours-adjoints"
  sujet_ref  = "BF-0001"
  finalite   = "vérification des conditions d'inscription au concours direct des adjoints administratifs"
} | ConvertTo-Json
$r = Invoke-RestMethod -Method Post -Uri "$MEDIATEUR/demandes" -Headers $entetes `
       -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($corps))
$r.statut
$r.volets | Select-Object attribut, registre, statut, motif

# 2. Suivi d'une demande avec consentement (l'usager confirme par USSD)
Invoke-RestMethod -Uri "$MEDIATEUR/demandes/$($r.id_demande)" -Headers $entetes

# 3. Rejeu : même id_demande -> même résultat, registres non rappelés
Invoke-RestMethod -Method Post -Uri "$MEDIATEUR/demandes" -Headers $entetes `
  -ContentType "application/json; charset=utf-8" -Body ([Text.Encoding]::UTF8.GetBytes($corps))
```

## 6. Contrôle (lecture seule)

Jeton d'un compte au rôle `controleur` (ex. `controle.cil`), mêmes vérifications :

- `GET /controle` : comptes de test actifs (oui / non), limites, état des registres, alertes et refus des
  registres (agent, service, motif ; **jamais** de citoyen ni de valeur), catalogue en vigueur et son empreinte.
- `GET /controle/verification` : même vérification que `journal/verifier.py --registres`.

Interface : `https://guichet.griot.test/controle`.
