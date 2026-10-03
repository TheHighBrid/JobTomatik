#!/usr/bin/env python3
"""Fail on npm production vulnerabilities outside reviewed, inapplicable findings."""

from __future__ import annotations
import json
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
PACKAGE_LOCK = ROOT / "frontend" / "package-lock.json"
ALLOWED_ADVISORY_URLS = {"https://github.com/advisories/GHSA-qwww-vcr4-c8h2"}
REVIEWED_FIXED_PACKAGE_ADVISORIES = {("axios", "1.20.0"): {"https://github.com/advisories/GHSA-542g-h47m-68v8","https://github.com/advisories/GHSA-3pq3-5fj3-cg6v","https://github.com/advisories/GHSA-x97p-jq2g-jp4f","https://github.com/advisories/GHSA-mghh-pgcx-3jjj","https://github.com/advisories/GHSA-c29m-xwm3-cm6r","https://github.com/advisories/GHSA-9fr6-4gfg-395g","https://github.com/advisories/GHSA-vh66-26gq-q6x8","https://github.com/advisories/GHSA-r4gj-5m52-g5wh","https://github.com/advisories/GHSA-44g4-m2mj-wpvx","https://github.com/advisories/GHSA-m8m8-qj5v-23w3","https://github.com/advisories/GHSA-4hqw-qxg8-jxx2","https://github.com/advisories/GHSA-j8rh-479h-cp32"}}
def _installed_package_versions() -> dict[str,str]:
    try: payload=json.loads(PACKAGE_LOCK.read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError): return {}
    packages=payload.get("packages")
    if not isinstance(packages,dict): return {}
    versions={}
    for key,value in packages.items():
        if isinstance(key,str) and key.startswith("node_modules/") and isinstance(value,dict) and isinstance(value.get("version"),str) and value.get("version"): versions[key.removeprefix("node_modules/")]=value["version"]
    return versions
def _advisory_is_reviewed_for_installed_package(package:str,url:str,installed_versions:dict[str,str])->bool:
    if url in ALLOWED_ADVISORY_URLS: return True
    version=installed_versions.get(package)
    return bool(version and url in REVIEWED_FIXED_PACKAGE_ADVISORIES.get((package,version),set()))
def main()->int:
    if len(sys.argv)!=2: print("usage: validate_npm_audit.py <npm-audit.json>",file=sys.stderr); return 2
    try: payload=json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    except (OSError,json.JSONDecodeError) as exc: print(f"Invalid npm audit report: {exc}",file=sys.stderr); return 2
    vulnerabilities=payload.get("vulnerabilities")
    if not isinstance(vulnerabilities,dict): print("Invalid npm audit report: vulnerabilities object missing",file=sys.stderr); return 2
    installed_versions=_installed_package_versions(); unapproved=[]; rejected_urls={}; observed_urls=set()
    for package,finding in vulnerabilities.items():
        package_name=str(package)
        if not isinstance(finding,dict): unapproved.append(package_name); continue
        via=finding.get("via")
        if not isinstance(via,list) or not via: unapproved.append(package_name); continue
        finding_is_approved=True
        for item in via:
            if isinstance(item,dict):
                url=item.get("url")
                if not isinstance(url,str) or not url: finding_is_approved=False; continue
                observed_urls.add(url)
                if not _advisory_is_reviewed_for_installed_package(package_name,url,installed_versions): rejected_urls.setdefault(package_name,set()).add(url); finding_is_approved=False
            elif isinstance(item,str):
                if not item or item not in vulnerabilities: finding_is_approved=False
            else: finding_is_approved=False
        if not finding_is_approved: unapproved.append(package_name)
    if unapproved:
        details=[]
        for package in sorted(set(unapproved)):
            urls=sorted(rejected_urls.get(package,set())); details.append(f"{package}=[{', '.join(urls)}]" if urls else package)
        print("Unapproved production npm vulnerabilities: "+"; ".join(details),file=sys.stderr); return 1
    if vulnerabilities and not observed_urls: print("Audit findings did not resolve to a reviewed advisory",file=sys.stderr); return 1
    if vulnerabilities: print("Production npm audit passed with reviewed exceptions: "+", ".join(sorted(observed_urls)))
    else: print("Production npm audit passed with no vulnerabilities")
    return 0
if __name__=="__main__": raise SystemExit(main())
