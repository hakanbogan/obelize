import numpy as np


def membership(values, allowed):
    return np.in1d(values, allowed), np.trapz(values), np.asfarray(values)


def by_column(values):
    return np.msort(values)
