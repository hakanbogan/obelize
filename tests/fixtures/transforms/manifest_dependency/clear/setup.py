"""Packaging for the fixture. The docstring names google-generativeai and is not
a declaration; the string inside install_requires is."""

from setuptools import setup

setup(
    name="clear-fixture",
    install_requires=[
        "google-generativeai==0.8.6",
        "requests>=2.31",
    ],
)
