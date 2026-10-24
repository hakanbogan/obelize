from pkg_resources import parse_version


def is_newer(found, wanted):
    return parse_version(found) > parse_version(wanted)
