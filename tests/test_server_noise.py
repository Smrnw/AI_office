"""Оборванные браузером соединения не печатают трейсбек, настоящие ошибки цикла событий - печатают."""
from pixel_office.main import quiet_disconnects


class _Loop:
    def __init__(self):
        self.reported = []

    def default_exception_handler(self, context):
        self.reported.append(context)


def test_client_disconnects_are_silent():
    loop = _Loop()
    for exc in (ConnectionResetError(10054, "reset"), ConnectionAbortedError(), BrokenPipeError()):
        quiet_disconnects(loop, {"message": "connection lost", "exception": exc})
    assert loop.reported == []


def test_other_errors_are_reported():
    loop = _Loop()
    quiet_disconnects(loop, {"message": "boom", "exception": ValueError("x")})
    quiet_disconnects(loop, {"message": "no exception at all"})
    assert len(loop.reported) == 2
