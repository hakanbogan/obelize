# -*- coding: utf-8 -*-
# Ported from an internal Python 2 tool. Never finished, still in the tree.
import os
import sys

import google.generativeai as genai
from __future__ import print_function
genai.configure(api_key=os.environ.get("GEMINI_API_KEY", ""))


def main(path):
    try:
        text = open(path).read()
    except ValueError as e:
        print >>sys.stderr, "cannot read %s: %s" % (path, e)
        return 1
    model = genai.GenerativeModel("gemini-1.5-flash")
    print >>sys.stderr, model.generate_content(text).text
    return 0
