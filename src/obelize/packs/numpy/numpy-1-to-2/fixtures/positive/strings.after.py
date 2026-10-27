import numpy as np

# A string is no name the scan reads: it stays as written, and NumPy 2 raises TypeError for it.
EMPTY = np.zeros(3, dtype="float_")
SCALAR = np.float64(1)
