"""A call rewritten by the shape of its arguments: one of a name, and one of a member."""

import acme.shapes
import acme.shapes as shapes
from acme.shapes import Shape


class Square(Shape):
    pass


def build(n, item: Square):
    acme.shapes.make_square(2)
    shapes.make_square(n + 1)
    item.render(3)
    Square().render(width_of(item))
    return (a + b).render(n)
