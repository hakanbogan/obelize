import numpy as np


def membership(values, allowed):
    return np.in1d(values, allowed), np.trapz(values), np.asfarray(values)
