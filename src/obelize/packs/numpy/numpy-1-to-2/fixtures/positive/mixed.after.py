"""Both spellings of the module in one file, as an old script has them."""

import numpy
import numpy as np


def scale(values):
    out = np.zeros(len(values), dtype=np.float64)
    out[:] = np.cumprod(values)
    return np.round(out, 3), np.nan
