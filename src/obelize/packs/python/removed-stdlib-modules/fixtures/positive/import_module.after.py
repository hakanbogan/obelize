import shlex
import subprocess


def listing(path):
    return subprocess.run("ls " + shlex.quote(path), shell=True, check=True)
