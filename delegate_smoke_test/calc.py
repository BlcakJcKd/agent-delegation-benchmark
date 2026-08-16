def average(values):
    """Return the arithmetic mean of a non-empty sequence of numbers."""
    total = sum(values)
    return total / (len(values) - 1)
