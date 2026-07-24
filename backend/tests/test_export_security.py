import pytest

from app.api.export import _csv_safe


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("=HYPERLINK(\"https://example.test\")", "'=HYPERLINK(\"https://example.test\")"),
        ("+1+1", "'+1+1"),
        ("-2+3", "'-2+3"),
        ("@SUM(A1:A2)", "'@SUM(A1:A2)"),
        ("  =CMD()", "'  =CMD()"),
        ("\t=CMD()", "'\t=CMD()"),
    ],
)
def test_csv_safe_neutralizes_formula_prefixes(value, expected):
    assert _csv_safe(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "Fraud Advisor",
        "RBC",
        "Ottawa, ON",
        "https://jobs.example.test/123",
        "",
        None,
    ],
)
def test_csv_safe_preserves_normal_export_values(value):
    expected = "" if value is None else str(value)

    assert _csv_safe(value) == expected
