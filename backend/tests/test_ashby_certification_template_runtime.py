import json
from pathlib import Path


def test_template_names_native_runtime():
    payload = json.loads(Path("docs/ashby-real-certification-evidence.example.json").read_text(encoding="utf-8"))
    assert payload["runtime"] == "android_native_chrome_cdp"
