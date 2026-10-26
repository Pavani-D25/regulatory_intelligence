"""Vehicle-segment picker (regtrack/segments.py): path -> category codes + usage."""

import pytest

from regtrack import segments


@pytest.mark.parametrize(("cc", "path", "expected"), [
    ("IN", "", None),
    ("IN", "2W", (["L1", "L2"], None)),
    ("TH", "2W", (["L1", "L3"], None)),
    ("IN", "2W/CV", (["L1", "L2"], "transport")),
    ("IN", "2W/PV/L2/transport", (["L2"], "transport")),
    ("IN", "4W", (["M1", "N1"], None)),
    ("IN", "4W/PV", (["M1"], None)),  # taxis / cabs are passenger vehicles
    ("IN", "4W/PV/M1/private", (["M1"], "private")),
    ("IN", "4W/CV", (["N1"], None)),
    ("MY", "4w/cv/n1/goods", (["N1"], None)),
])
def test_resolve(cc, path, expected):
    assert segments.resolve(cc, path) == expected


@pytest.mark.parametrize("path", ["3W", "4W/PV/N1", "2W/PV/L3"])
def test_unknown_path(path):
    with pytest.raises(ValueError):
        segments.resolve("IN", path)


def test_usage_sql():
    assert segments.usage_sql("d", None) == ""
    assert "ARRAY['transport','all']" in segments.usage_sql("m", "transport")
    with pytest.raises(ValueError):
        segments.usage_sql("d", "x'; DROP")
