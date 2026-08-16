def fetch_cached(store: dict, key: str, factory):
    value = store.get(key)
    if not value:
        value = factory()
        store[key] = value
    return value
