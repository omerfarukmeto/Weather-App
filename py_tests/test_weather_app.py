import pytest
import weather_app as app


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (0, "Clear sky"),
        (999, "Code 999"),
        (None, "Unknown"),
    ],
)
def test_weather_description(code, expected):
    assert app.weather_description(code) == expected
import sys
from urllib.error import URLError


@pytest.mark.parametrize(
    "args",
    [
        ["--days", "0"],
        ["--days", "17"],
        ["--temperature-unit", "kelvin"],
        ["--wind-unit", "beaufort"],
    ],
)

def test_parse_args_rejects_invalid_options(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["weather_app.py", *args])

    with pytest.raises(SystemExit) as exc_info:
        app.parse_args()

    assert exc_info.value.code == 2


def test_choose_location_rejects_no_matches():
    with pytest.raises(RuntimeError, match="No matching location found"):
        app.choose_location([])


def test_get_json_reports_network_error(monkeypatch):
    def fail_request(*args, **kwargs):
        raise URLError("offline")

    monkeypatch.setattr(app, "urlopen", fail_request)

    with pytest.raises(RuntimeError, match="Could not reach the weather service"):
        app.get_json("https://example.test", {})