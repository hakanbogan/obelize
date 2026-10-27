import numpy as np

SCALAR = np.float64(1.5)
DTYPE = np.dtype(np.complex128)
WIDE = np.longdouble(2)
SMALL = np.complex64(1)
LONG = np.clongdouble(1)
OLD_LONG = np.clongdouble(1)
SHORT = np.complex128(1)
RAW = np.bytes_("raw")
TEXT = np.str_("text")


def empty(shape):
    return np.zeros(shape, dtype=np.float64)


def is_float(value) -> bool:
    return isinstance(value, np.float64)
