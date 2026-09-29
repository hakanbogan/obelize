# -*- coding: latin-1 -*-
"""Génère un résumé court d'un texte."""
import os

from google import genai

client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY", ""))

ENTETE = "Résumé du dossier « café » à Genève : "


def resumer(texte):
    return client.models.generate_content(model="gemini-1.5-flash", contents=ENTETE + texte).text
