"""Simple calculator with add function and pytest tests."""


def add(a: int, b: int) -> int:
    """Return the sum of two numbers."""
    return a + b


# --------------- tests ---------------

def test_add_positive_numbers():
    assert add(2, 3) == 5

def test_add_negative_numbers():
    assert add(-1, -1) == -2

def test_add_zero():
    assert add(0, 0) == 0

def test_add_mixed():
    assert add(-1, 1) == 0
