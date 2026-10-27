"""The names NumPy 2 keeps: np.float_ and np.in1d are mentioned here, and used nowhere."""

import numpy as np

SCALAR = np.float64(1.5)
NAN = np.nan
ROUNDED = np.round(np.cumprod(np.arange(1, 4)) / 3, 2)
SEEN = np.isin([1, 2], [2]).ravel()
