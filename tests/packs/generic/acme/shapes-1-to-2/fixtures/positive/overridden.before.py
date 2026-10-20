"""A class that defines the member itself: renaming it would run another function."""

from acme.shapes import Shape


class Square(Shape):
    def old_area(self):
        return 4


class Cube(Square):
    pass


def total():
    return Cube().old_area()
