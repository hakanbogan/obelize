import pkg_resources

__version__ = pkg_resources.get_distribution("demo").version

try:
    pkg_resources.require("requests>=2")
except pkg_resources.DistributionNotFound:
    raise SystemExit("requests is not installed")
