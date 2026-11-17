# Scénario : Aminata demande un passeport ordinaire

Personne et données **fictives**. Pour Aminata, le parcours est tiré du code de `main` (commit `053d043`). Pour
la démo écran par écran : [test-manuel.md](test-manuel.md), scène 1.

## Le contexte

Depuis le 29 janvier 2025, le passeport AES est en circulation ; c'est l'ONI qui le produit
([Sidwaya](https://www.sidwaya.info/retro-2025-carte-et-passeport-aes-larsenal-identitaire-de-lespace-sahelien-operationnel/),
[Sidwaya](https://www.sidwaya.info/?p=148180)).

Aminata Kaboré a 25 ans. Son identifiant fictif est `BF-0001`. Elle a un téléphone simple, sans Internet.

## Avant : le dossier classique

Le communiqué de 2017 sur le passeport ordinaire demandait, entre autres pièces : un **acte de naissance**, un
**certificat de nationalité**, la **CNIB** et un **extrait de casier judiciaire**
([Wakatsera](https://www.wakatsera.com/burkina-faso-les-conditions-dobtention-dun-passeport-ordinaire/)).
C'est ce que nous appelons **le dossier classique**. Ce n'est pas forcément la règle d'aujourd'hui.

Avec ce dossier, chaque pièce vient d'une administration différente. Aminata va donc d'un guichet à l'autre pour
les obtenir, puis les apporte au service des passeports. Et chaque pièce dit **beaucoup plus** que ce dont le
service a besoin :

- l'acte de naissance donne sa date et son lieu de naissance, et le nom de ses parents ;
- l'extrait de casier montre **toutes** les condamnations, même celles qui ne concernent pas un passeport.

Ensuite, Aminata ne sait pas qui a regardé ces papiers, ni ce qu'on en a fait.

## Après : avec Griot Secure

### 1. Au guichet des passeports

Moussa Koné (`moussa.kone`), agent du **Service des passeports – ONI**, se connecte avec son mot de passe et un
code à 6 chiffres, qui change toutes les 30 secondes. Il choisit **« Passeport ordinaire »**, tape `BF-0001` et
envoie.

Il ne peut rien demander d'autre : le catalogue fixe les deux questions de cette démarche. Et il ne choisit pas
son service : le système le lit dans son compte.

Son écran affiche : **« En attente de l'usager. Il voit exactement ce qui sera transmis et doit confirmer.
Rien n'est encore transmis. »**

### 2. Les registres répondent, sans rien envoyer de plus

Le médiateur pose deux questions **en même temps** :

- au registre de la **nationalité** : « Aminata est-elle burkinabè ? » ;
- au **casier judiciaire** : « Y a-t-il une interdiction de sortie du territoire ? ».

L'état civil n'est **pas** interrogé : le catalogue ne demande pas l'âge pour le passeport.

Chaque registre vérifie lui-même que c'est bien un agent des passeports qui demande, et que ce service a le droit
de poser cette question. Il répond seulement « oui » ou « non », **signé** avec sa propre clé. La fiche reste
chez lui.

### 3. Aminata voit avant

Sur son téléphone, elle compose `*226#`, puis son code PIN, et choisit `1. Demandes en attente`. Elle lit :

> L'ONI (passeports) recevra : burkinabè = oui ; interdiction de sortie du territoire = non. Rien d'autre.
> 1\. Confirmer 2. Refuser

Elle tape `1`. Le téléphone répond : **« Confirmé. Reçu : xxxx xxxx xxxx xxxx »** (16 caractères).

Pour la loi n°001-2021/AN, ce consentement doit être « exprès, libre, spécifique et éclairé »
([source](https://assembleenationale.bf/storage/Loi/kDsWHXOTUCQFVESChh8BlBdiZnCrdTsOpXe1rzmH.pdf)). Aminata
sait exactement ce qui part, à qui, et pourquoi : « établissement d'un passeport ordinaire ».

### 4. Le guichet reçoit la réponse utile

Moussa clique sur **Actualiser**. Il voit :

- **burkinabè : oui**, signé par le registre de la nationalité, signature vérifiée ;
- **interdiction de sortie du territoire : non**, signé par le casier judiciaire, signature vérifiée ;
- **Conclusion : toutes les conditions sont vérifiées.**

Le guichet a revérifié lui-même chaque signature. L'ONI n'a reçu ni date de naissance, ni nom des parents, ni
casier. Il ne sait même pas si le casier d'Aminata est vierge : il sait seulement qu'il n'y a pas d'interdiction
de sortie du territoire.

### 5. Aminata vérifie après

Plus tard, elle choisit `2. Qui a consulté mes données`. Elle voit la date, le service, la finalité, la base
(« Avec votre accord ») et son reçu. Elle ne voit **jamais** la valeur, car le journal ne la contient pas.

Avec le reçu, n'importe quel contrôleur peut retrouver la ligne dans le journal et vérifier que personne ne l'a
modifiée (`journal/verifier.py --recu`).

### Ce que Griot Secure ne change pas

Griot Secure ne remplace que **la collecte des pièces justificatives**. Le reste de la procédure du passeport
n'est pas traité par le prototype.

## Si les choses se passent autrement

| Situation | Ce qui se passe |
|---|---|
| Aminata tape `2` (Refuser) | « Refusé. Rien n'a été transmis. » Au guichet : refusé par l'usager |
| Aminata ne répond pas pendant 10 minutes | La demande expire, rien n'est remis |
| Elle retire son accord avant la remise (menu `3`) | « Accord retiré. Rien n'a été transmis. » |
| Elle retire son accord **après** la remise | « Accord retiré. Déjà transmis : le service ne doit plus l'utiliser. » Le système le dit honnêtement |
| Le casier contient une interdiction de sortie (citoyen fictif `BF-0008`) | « interdiction de sortie du territoire : oui » ; « au moins une condition n'est pas remplie ». L'ONI n'apprend rien des autres condamnations |
| Le casier a une case vide au lieu de « aucune » (`BF-0015`) | Le casier refuse de répondre : il ne devine pas qu'une case vide veut dire « aucune ». Au guichet : « résultat incomplet, aucune conclusion. Rien n'a été deviné » |
| Le registre de la nationalité est en panne | Cette ligne : « indisponible ». L'aperçu ne montre que ce qui partira vraiment. Au guichet : « résultat incomplet », jamais un « oui » global |
| Quelqu'un modifie le catalogue pour faire passer le passeport en « base légale » (sans accord) | Refusé au chargement du catalogue, et par les registres eux-mêmes : pour ce service, ils n'acceptent que l'accord de l'usager |
| Aminata est mineure | Non traité par le prototype : le consentement du représentant légal est noté dans [LIMITES.md](../LIMITES.md) |
