import cgi


def read(environ):
    form = cgi.FieldStorage(environ=environ)
    return form.getvalue("name")
