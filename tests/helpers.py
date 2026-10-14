def set_pay(cfg, code, min=None, big=None):
    """Set a country's pay row (local currency) in a test config."""
    rows = cfg["search"].setdefault("pay_by_country", {})
    row = rows.setdefault(code, {"min": 90000, "big": 70000})
    if min is not None:
        row["min"] = min
    if big is not None:
        row["big"] = big
    return cfg
