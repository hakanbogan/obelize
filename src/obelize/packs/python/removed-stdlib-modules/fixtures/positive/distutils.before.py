from distutils.spawn import find_executable
from distutils.version import LooseVersion


def compiler():
    return find_executable("cc")


def newer(found, wanted):
    return LooseVersion(found) > LooseVersion(wanted)
