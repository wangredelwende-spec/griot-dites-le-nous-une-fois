"""Minimisation : calcul de l'attribut minimal (« majeur : oui »), jamais l'enregistrement brut.

Ce paquet est écrit UNE fois dans la couche « consentement et minimisation » et exécuté DANS LE CONTENEUR DU
REGISTRE (il est copié dans son image) : la fiche du citoyen ne quitte donc jamais le registre. L'adaptateur du
registre (registres/app/adaptateur.py) retrouve la fiche, puis appelle `calculer` : seule la réponse minimale sort.
"""
from .ages import age_le, age_minimum_atteint, bornes_de_naissance, normaliser  # noqa: F401
from .refus import Refus  # noqa: F401
from .regles import calculer, egal, normaliser_texte  # noqa: F401
