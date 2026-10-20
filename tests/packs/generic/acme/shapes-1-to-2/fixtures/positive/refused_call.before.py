"""A call that passes a keyword the new spelling lacks, which is left for a person."""

from acme.shapes import Shape


class Square(Shape):
    pass


def dump(item: Square):
    return item.to_dict(depth=1)
