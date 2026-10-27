import numpy as np


def summarise(values):
    everything = np.all(values > 0)
    anything = np.any(values > 1)
    running = np.cumprod(values)
    total = np.prod(values, axis=0)
    rounded = np.round(values / 3, decimals=2)
    stacked = np.vstack((values, values))
    return everything, anything, running, total, rounded, stacked


def as_matrix(rows):
    return np.asmatrix(rows)


APPLY = map(np.round, [1.234, 5.678])
