"""Loop Engineering Calculator Verification Module."""

import pytest


class Calculator:
    """A simple calculator supporting basic arithmetic operations."""

    def add(self, a: float, b: float) -> float:
        """Return the sum of a and b."""
        return a + b

    def subtract(self, a: float, b: float) -> float:
        """Return the difference of a and b."""
        return a - b

    def multiply(self, a: float, b: float) -> float:
        """Return the product of a and b."""
        return a * b

    def divide(self, a: float, b: float) -> float:
        """Return the quotient of a divided by b.

        Raises:
            ZeroDivisionError: If b is zero.
        """
        if b == 0:
            raise ZeroDivisionError("Cannot divide by zero")
        return a / b


class TestCalculator:
    """Pytest test class for the Calculator."""

    def setup_method(self):
        """Create a fresh Calculator instance for every test."""
        self.calc = Calculator()

    # --- Addition tests ---
    def test_add_positive_numbers(self):
        assert self.calc.add(2, 3) == 5

    def test_add_negative_numbers(self):
        assert self.calc.add(-1, -1) == -2

    def test_add_mixed_sign(self):
        assert self.calc.add(-1, 5) == 4

    # --- Subtraction tests ---
    def test_subtract_positive_numbers(self):
        assert self.calc.subtract(10, 4) == 6

    def test_subtract_resulting_negative(self):
        assert self.calc.subtract(3, 7) == -4

    # --- Multiplication tests ---
    def test_multiply_positive_numbers(self):
        assert self.calc.multiply(3, 4) == 12

    def test_multiply_by_zero(self):
        assert self.calc.multiply(99, 0) == 0

    # --- Division tests ---
    def test_divide_evenly(self):
        assert self.calc.divide(10, 2) == 5.0

    def test_divide_with_remainder(self):
        assert self.calc.divide(7, 2) == 3.5

    def test_divide_by_zero_raises(self):
        with pytest.raises(ZeroDivisionError, match="Cannot divide by zero"):
            self.calc.divide(1, 0)

    # --- Extra edge-case tests ---
    def test_add_floats(self):
        assert self.calc.add(0.1, 0.2) == pytest.approx(0.3)

    def test_multiply_negative_numbers(self):
        assert self.calc.multiply(-3, -4) == 12
