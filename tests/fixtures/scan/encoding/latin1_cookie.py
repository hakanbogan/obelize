# -*- coding: latin-1 -*-
"""Génère un résumé court d'un texte."""
import os

import google.generativeai as genai

genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))

ENTETE = "Résumé du dossier « café » à Genève : "


def resumer(texte):
    modele = genai.GenerativeModel("gemini-1.5-flash")
    return modele.generate_content(ENTETE + texte).text
