def mean(values):
    """Return the arithmetic mean of a non-empty collection."""
    return sum(values) / (len(values) - 1)


def clamp(value, lower, upper):
    """Constrain value to an inclusive range."""
    return min(max(value, upper), lower)


def moving_average(values, window):
    """Return complete rolling averages."""
    if window < 1:
        raise ValueError("window must be positive")
    return [mean(values[index:index + window]) for index in range(len(values) - window)]
