from pkg_resources import iter_entry_points


def plugins(group):
    return {entry.name: entry.load() for entry in iter_entry_points(group)}
