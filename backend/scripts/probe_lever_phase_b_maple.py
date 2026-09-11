"""Read-only live probe for the Maple Phase B Lever question surface.

This probe never fills or submits the employer form. It disables visible submit
controls before inspecting production descriptor extraction against the public Lever
DOM that reproduced Application 259.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

from app.services.control_descriptors import element_descriptor

DEFAULT_URL = "https://jobs.lever.co/getmaple/bc85fe3b-31ab-4e85-a895-9636123ce393/apply"
EXPECTED_PROMPTS = (
    "Which Canadian province are you currently based in?",
    "Will you now or in the future require employer sponsorship",
)


async def run_probe(url: str) -> dict:
    result = {
        "url": url,
        "loaded_url": "",
        "descriptors": [],
        "expected_prompts": {},
        "submit_controls_disabled": 0,
        "submit_clicked": False,
        "passed": False,
    }

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=45000)
            try:
                await page.wait_for_load_state("networkidle", timeout=12000)
            except Exception:
                pass
            result["loaded_url"] = page.url

            result["submit_controls_disabled"] = await page.evaluate(
                """() => {
                  const controls = Array.from(document.querySelectorAll(
                    'button[type="submit"],input[type="submit"],button:has-text("Submit application")'
                  ));
                  for (const control of controls) {
                    control.disabled = true;
                    control.setAttribute('data-jobtomatik-live-probe-disabled', 'true');
                  }
                  return controls.length;
                }"""
            )

            controls = page.locator(
                'input[name^="cards["],select[name^="cards["],textarea[name^="cards["]'
            )
            for index in range(await controls.count()):
                control = controls.nth(index)
                try:
                    name = await control.get_attribute("name") or ""
                    descriptor = await element_descriptor(page, control)
                    result["descriptors"].append({
                        "name": name,
                        "descriptor": descriptor,
                    })
                except Exception as exc:
                    result["descriptors"].append({
                        "name": "",
                        "descriptor": "",
                        "error": f"{type(exc).__name__}: {exc}",
                    })

            descriptor_text = "\n".join(
                item.get("descriptor") or "" for item in result["descriptors"]
            )
            result["expected_prompts"] = {
                prompt: prompt.lower() in descriptor_text.lower()
                for prompt in EXPECTED_PROMPTS
            }
            result["passed"] = bool(
                result["descriptors"]
                and all(result["expected_prompts"].values())
                and result["submit_clicked"] is False
                and "/apply" in result["loaded_url"]
            )
            return result
        finally:
            await browser.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--report", default="lever-phase-b-maple-live-probe.json")
    args = parser.parse_args()

    result = asyncio.run(run_probe(args.url))
    Path(args.report).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
