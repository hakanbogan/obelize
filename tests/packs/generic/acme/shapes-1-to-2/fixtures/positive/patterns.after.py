"""A call rewritten by the shape of its arguments: one of a name, and one of a member."""

import acme.shapes
import acme.shapes as shapes
from acme.shapes import Shape


class Square(Shape):
    pass


def build(n, item: Square):
    acme.shapes.Square(side=2)
    shapes.Square(side=n + 1)
    item.draw(width=3)
    Square().draw(width=width_of(item))
    return (a + b).render(n)
