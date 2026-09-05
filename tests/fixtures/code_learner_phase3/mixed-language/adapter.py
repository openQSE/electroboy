from ctypes import CDLL


def load_native(path):
    return CDLL(path)


def scale(library, value):
    return library.native_scale(value)
