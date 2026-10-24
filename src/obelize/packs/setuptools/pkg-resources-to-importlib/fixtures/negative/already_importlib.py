from importlib import metadata, resources

__version__ = metadata.version("demo")


def plugins(group):
    return {entry.name: entry.load() for entry in metadata.entry_points(group=group)}


def template(name):
    return (resources.files(__package__) / "templates" / name).read_text(encoding="utf-8")
