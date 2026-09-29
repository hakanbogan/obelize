"""A flagged shape in a file that is refused for a second, wider reason.

The alias is read as a bare value, so `module_alias_rebound` withholds every
row in the file that has nothing more specific to say. It does not reach the
dynamic access: `flag_only_surface` is rung 1 of SCAN_VOCABULARY.md section 6
and nothing displaces it, which is what makes this rule's claim independent of
whatever else is wrong with the file.
"""

import importlib

import google.generativeai as genai


def module():
    return genai


def loaded():
    return importlib.import_module("google.generativeai")
