"""Calls of the patterns' names in shapes the patterns do not cover, left for a person."""

import acme.shapes
from acme.shapes import Shape, make_square


class Square(Shape):
    pass


def build(item: Square):
    acme.shapes.make_square(2, extra=1)
    make_square(3)
    return item.render(width=3)
