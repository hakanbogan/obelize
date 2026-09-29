"""Packaging for the fixture."""

from setuptools import setup

setup(
    name="blocked-fixture",
    install_requires=[
        "google-generativeai==0.8.6",
        "requests>=2.31",
    ],
)
