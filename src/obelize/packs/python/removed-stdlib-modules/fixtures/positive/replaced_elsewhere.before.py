import imghdr
import pipes
import telnetlib


def kind(path):
    return imghdr.what(path)


def chain():
    return pipes.Template()


def banner(host):
    with telnetlib.Telnet(host) as connection:
        return connection.read_until(b"\n")
