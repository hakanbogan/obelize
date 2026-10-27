import numpy as np

# `-np.inf ** 2` is `-(np.inf ** 2)`, which is not `np.NINF ** 2`.
SQUARE = np.NINF ** 2
