"""A member acme-shapes 2 dropped, read off an instance of a derived class: reported only."""

from acme.shapes import Shape


class Square(Shape):
    pass


def check(item: Square):
    return item.retired
