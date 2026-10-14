import pytest

from jobhunter import settings


@pytest.fixture
def full_form():
    """full_form(cfg, "matching", **{"search.min_salary": "85000"}) -> a complete, valid POST body for that settings page,
    built from the current config, with the given fields overridden. New settings never break tests that use it."""
    def build(cfg, section_id, **override):
        form = {}
        for f in settings.SECTION_BY_ID[section_id].fields:
            val = settings.get_path(cfg, f.path)
            if f.kind == "bool":
                if val:
                    form[f.path] = "on"
            elif f.kind == "choices":
                form[f.path] = [str(v) for v in val]
            else:
                form[f.path] = settings.to_text(f, val)
        for k, v in override.items():
            if v is None:
                form.pop(k, None)
            else:
                form[k] = v
        return form
    return build
