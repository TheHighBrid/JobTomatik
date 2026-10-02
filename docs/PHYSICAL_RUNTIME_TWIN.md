# JobTomatik Physical Runtime Twin

## Purpose

GitHub CI is a fast regression gate, not proof that JobTomatik works on the owner's real Android lane. The physical runtime twin exists to close that gap.

The authoritative production-shaped environment is Android/ARM64 with Termux, Ubuntu PRoot where required by the application stack, ADB transport, native Android Chrome, the `chrome_devtools_remote` socket forwarded to the managed loopback CDP endpoint, and the same JobTomatik revision and runtime contracts used by the launcher/API/worker.

A future statement that a browser/runtime acceptance test "passed" must identify which tier produced the evidence. CI-only evidence must never be described as physical-runtime validation.

## Evidence tiers

1. **Unit/CI**: deterministic logic and regression tests. Useful, but not a device result.
2. **Contract twin**: captured physical-environment manifest plus production-shaped fixtures and fault injection. Detects architecture, transport, endpoint, and browser-identity drift.
3. **Physical twin**: tests executed on the actual Android/Termux/ADB/native-Chrome lane. This is the acceptance authority for device-dependent behavior.
4. **Supervised production proof**: a real retained application workflow where policy permits it. This remains separate from automated certification.

## Initial implementation

`backend/scripts/jobtomatik_runtime_twin.py` captures a machine-readable manifest of the environment. In strict mode it fails when the runner is not Android ARM64, ADB is unavailable, or native Chrome CDP is unreachable. It can compare a current capture with a retained known-good manifest.

Capture a known-good physical baseline:

```bash
python backend/scripts/jobtomatik_runtime_twin.py \
  --endpoint http://127.0.0.1:9223 \
  --output backend/.runtime/physical-twin-baseline.json \
  --strict
```

Compare a later run to that baseline:

```bash
python backend/scripts/jobtomatik_runtime_twin.py \
  --endpoint http://127.0.0.1:9223 \
  --compare backend/.runtime/physical-twin-baseline.json \
  --strict
```

The baseline belongs under `backend/.runtime/`, not source control, because it describes the current physical device and transport.

## Next implementation slice

The next slice is an executable acceptance harness that drives the same `jobtomatik` launcher and application worker against a local deterministic Lever-like fixture through the attached native Chrome. It must prove tab creation, field population, retained operator handoff, page-target identity, disconnect/reconnect behavior, confirmation reconciliation, and duplicate suppression. Fault injection must cover ADB loss, forward loss, stale CDP, Chrome target replacement, worker restart, and retained-page recovery.

The harness must retain JSON evidence containing the repository revision, runtime-twin manifest hash, test scenario, browser target identity, timestamps, result, and failure reason. Only a green physical-twin receipt can support the phrase `PHYSICAL_RUNTIME_TWIN: PASS`.
