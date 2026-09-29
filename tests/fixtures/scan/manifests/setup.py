"""Packaging for the legacy helpers.

The distribution pins google-generativeai, and the declaration is below.
"""

from setuptools import setup

setup(
    name="legacy-helpers",
    keywords=["gemini", "google.generativeai"],
    install_requires=[
        "google-generativeai==0.8.6",
        "requests>=2.31",
    ],
    extras_require={"dev": ["pytest>=8.3"]},
)
