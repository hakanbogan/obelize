import pipes
import subprocess


def listing(path):
    return subprocess.run("ls " + pipes.quote(path), shell=True, check=True)
