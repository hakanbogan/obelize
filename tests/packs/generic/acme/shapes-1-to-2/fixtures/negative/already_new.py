"""Code on acme-shapes 2 already, and a receiver nothing says is a Shape: both left alone."""

from __future__ import annotations

import acme.shapes
from acme.shapes import Shape


class Square(Shape):
    def double(self):
        return self.area() * 2


def measure(item: Square, other):
    other.old_area()
    return item.area(), item.as_dict(), acme.shapes.Shape.area, acme.shapes.Square(side=1), item.draw(width=2)
