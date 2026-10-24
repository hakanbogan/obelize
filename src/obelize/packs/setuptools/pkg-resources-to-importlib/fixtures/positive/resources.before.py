import pkg_resources

SCHEMA = pkg_resources.resource_filename("demo", "data/schema.json")


def template(name):
    return pkg_resources.resource_string(__name__, "templates/" + name).decode("utf-8")
