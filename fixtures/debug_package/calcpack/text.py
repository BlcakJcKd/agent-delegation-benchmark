import re


def slugify(value):
    """Make a lower-case, hyphenated identifier."""
    value = re.sub(r"[^a-z0-9]+", "-", value.lower())
    return value.strip("_")
