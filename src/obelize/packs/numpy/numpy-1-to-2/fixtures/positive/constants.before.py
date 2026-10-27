import numpy


def clean(values):
    values = numpy.nan_to_num(values, nan=numpy.NaN, posinf=numpy.PINF)
    return numpy.where(values == numpy.Inf, numpy.NAN, values)


LIMITS = (numpy.Infinity, numpy.infty)
