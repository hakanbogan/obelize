import numpy


def clean(values):
    values = numpy.nan_to_num(values, nan=numpy.nan, posinf=numpy.inf)
    return numpy.where(values == numpy.inf, numpy.nan, values)


LIMITS = (numpy.inf, numpy.inf)
