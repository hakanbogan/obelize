from pipes import quote


def command(*words):
    return " ".join(quote(word) for word in words)
