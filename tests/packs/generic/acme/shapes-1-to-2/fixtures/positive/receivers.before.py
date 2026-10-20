"""Every way a value is known to be a Shape, or an instance of a class derived from one."""

from __future__ import annotations

from typing import Optional

import acme.shapes
from acme.shapes import Shape


class Square(Shape):
    side: float = 1.0

    def double(self):
        return self.old_area() * 2

    @classmethod
    def unit(cls):
        return cls.to_dict

    @staticmethod
    def helper(value):
        return value.old_area()


class Circle(acme.shapes.Shape):
    pass


class Ring(Circle):
    def outline(self):
        return self.to_dict()


shape = Square()
shape.old_area()


def measure(item: Square, other: "Circle", maybe: Optional[Ring] = None):
    item.old_area()
    other.to_dict()
    maybe.old_area()
    local = Circle()
    local.to_dict()
    return Square().old_area(), Square.to_dict, shape.old_area


def through_the_library(item):
    return acme.shapes.Shape.old_area(item), Shape.to_dict
