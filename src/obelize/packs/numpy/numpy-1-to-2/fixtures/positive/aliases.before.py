import numpy as np

SCALAR = np.float_(1.5)
DTYPE = np.dtype(np.complex_)
WIDE = np.longfloat(2)
SMALL = np.singlecomplex(1)
LONG = np.longcomplex(1)
OLD_LONG = np.clongfloat(1)
SHORT = np.cfloat(1)
RAW = np.string_("raw")
TEXT = np.unicode_("text")


def empty(shape):
    return np.zeros(shape, dtype=np.float_)


def is_float(value) -> bool:
    return isinstance(value, np.float_)
