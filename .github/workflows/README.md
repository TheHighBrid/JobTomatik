# Workflow map

The repository's canonical local and CI verification entry point is `scripts/verify.sh`.

`reproducible-verification.yml` executes the complete clean-reproduction contract in independent lanes and joins them through one aggregate release gate. Specialized workflows remain responsible for adapter certification, recovery drills, evidence review, security analysis, and release publication.

When a specialized workflow duplicates a toolchain version, it must match `.jobtomatik-toolchain.env` and the contract test in `backend/tests/test_reproducible_verification_contract.py`.
