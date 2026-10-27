"""Both spellings of the module in one file, as an old script has them."""

import numpy
import numpy as np


def scale(values):
    out = np.zeros(len(values), dtype=np.float_)
    out[:] = numpy.cumproduct(values)
    return np.round_(out, 3), np.NaN
