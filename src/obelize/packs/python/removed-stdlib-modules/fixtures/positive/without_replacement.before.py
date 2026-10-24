import audioop
import xdrlib


def loudest(fragment):
    return audioop.max(fragment, 2)


def pack_int(value):
    packer = xdrlib.Packer()
    packer.pack_int(value)
    return packer.get_buffer()
