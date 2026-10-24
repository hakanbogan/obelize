class Clock:
    """Its own `utcnow`: nothing here comes from the datetime module."""

    def utcnow(self):
        return 0


class datetime:
    @staticmethod
    def utcnow():
        return 1


now = Clock().utcnow() + datetime.utcnow()
