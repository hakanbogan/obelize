import numpy as np


def summarise(values):
    everything = np.alltrue(values > 0)
    anything = np.sometrue(values > 1)
    running = np.cumproduct(values)
    total = np.product(values, axis=0)
    rounded = np.round_(values / 3, decimals=2)
    stacked = np.row_stack((values, values))
    return everything, anything, running, total, rounded, stacked


def as_matrix(rows):
    return np.mat(rows)


APPLY = map(np.round_, [1.234, 5.678])
