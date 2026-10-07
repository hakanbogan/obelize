"""Names pypdf no longer defines: obelize reports them and edits nothing."""

import PyPDF2


def merge(paths, target):
    merger = PyPDF2.PdfMerger()
    for path in paths:
        merger.append(path)
    merger.write(target)
