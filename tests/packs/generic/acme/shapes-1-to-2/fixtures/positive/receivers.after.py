"""Every way a value is known to be a Shape, or an instance of a class derived from one."""

from __future__ import annotations

from typing import Optional

import acme.shapes
from acme.shapes import Shape


class Square(Shape):
    side: float = 1.0

    def double(self):
        return self.area() * 2

    @classmethod
    def unit(cls):
        return cls.as_dict

    @staticmethod
    def helper(value):
        return value.old_area()


class Circle(acme.shapes.Shape):
    pass


class Ring(Circle):
    def outline(self):
        return self.as_dict()


shape = Square()
shape.area()


def measure(item: Square, other: "Circle", maybe: Optional[Ring] = None):
    item.area()
    other.as_dict()
    maybe.area()
    local = Circle()
    local.as_dict()
    return Square().area(), Square.as_dict, shape.area, shape.as_dict(indent=2)


def through_the_library(item):
    return acme.shapes.Shape.area(item), Shape.as_dict
