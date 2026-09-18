# Lever Promotion Evidence Runtime Lane

Date: 2026-09-17

Tracking: #514

## Purpose

The completed September Phase B objective sprint remains frozen at certification
revision `198b197dfcece6fbf9f3edfc5a92511fd951b484`. Real supervised submissions
needed for the separate Lever maturity gate must not mutate that checkout, its SQLite
database, native Chromium profile, queue state, filesystem state, or retained objective
history.

`backend/scripts/jobtomatik_promotion_lane.sh` creates a second, isolated execution
lane for new promotion evidence while preserving the frozen lane as a rollback target.
State preparation is implemented in
`backend/scripts/prepare_lever_promotion_lane_state.py` so the database snapshot,
ledger carry-forward, environment rewrite, and path isolation are directly testable.

These helpers do **not** arm the supervised pilot, issue an application approval,
queue an application, click final Submit, or enable any persistent submit/autopilot
flag.

## Isolation model

The promotion lane uses:

- source-of-truth frozen checkout: `/root/JobTomatik` at exact revision `198b197d...`;
- current-main sibling worktree: `/root/JobTomatik-promotion`;
- promotion database: `backend/jobtomatik-promotion.db`;
- promotion-local mutable state under `backend/.promotion-state/`;
- promotion native runtime state: `~/.jobtomatik-promotion-runtime`;
- promotion Chromium profile: `~/.jobtomatik-promotion-chromium`;
- browser node identity `promotion-evidence-node`, so old retained frozen sessions cannot
  silently satisfy the promotion browser-affinity contract;
- frozen Android broker `redis://localhost:6379/1`;
- promotion-only native Redis server on `127.0.0.1:6380`, used as
  `redis://localhost:6380/1` by the promotion API/worker/Beat;
- the standard localhost API/frontend/CDP ports, but only after the frozen stack has
  been stopped;
- the standard pilot-control `/tmp` bus, with its transient files archived between
  lane switches so no request is replayed across lanes.

Only one JobTomatik stack is active at a time. The promotion Redis process is separately
PID-identified and never signals an unrelated Redis process.

## Queue isolation

Stopping the frozen worker does not prove its Redis queues are empty, so the promotion
lane never consumes the frozen broker. The helper starts a promotion-only Redis daemon
on port `6380`, verifies the daemon PID identity, and flushes only promotion DB 1 before
starting the promotion worker. This guarantees that a prior frozen `applications`,
`followup`, `scraping`, or default `celery` task cannot cross into the promotion lane.

The promotion SQLite database and Lever evidence ledger are durable. Promotion Redis
queue contents are deliberately ephemeral and are not treated as evidence. The helper
stops the promotion Redis daemon when the promotion lane stops or returns to frozen.
If port 6380 is already served by an unmanaged Redis process, startup fails closed.

## Retained Lever confirmation evidence

The frozen runtime's configured `LEVER_PILOT_LEDGER_PATH` is authoritative for already
accepted real Lever confirmation evidence. The promotion lane requires that ledger to
exist and contain at least one structurally valid supervised Phase B record before it
will prepare.

The ledger is copied into:

`backend/.promotion-state/evidence/lever-pilot-ledger.jsonl`

The source file is never shared by writable inode and is never rewritten. The initial
record count and SHA-256 are captured in the ignored promotion-lane receipt. Later
promotion confirmations may append to the isolated copy. Re-entry verification permits
the isolated ledger to grow but refuses any state where its valid-record count falls
below the initial retained count.

This preserves Maple application 247 as the existing real confirmation without
relabeling the separate September 10/10 no-submit objective sprint.

## Filesystem path isolation

A copied `.env` is not trusted as-is. Mutable path settings are rewritten into the
promotion worktree even if the frozen runtime used absolute paths:

- `UPLOAD_DIR=.promotion-state/uploads`
- `HANDOFF_STORAGE_DIR=.promotion-state/handoff_sessions`
- `APPLICATION_BROWSER_PROFILE_DIR=.promotion-state/browser_profiles/jobtomatik-operator`
- `GREENHOUSE_PILOT_LEDGER_PATH=.promotion-state/evidence/greenhouse-pilot-ledger.jsonl`
- `GREENHOUSE_PILOT_READINESS_JSON_PATH=.promotion-state/evidence/greenhouse-pilot-readiness.json`
- `GREENHOUSE_PILOT_READINESS_MARKDOWN_PATH=.promotion-state/evidence/greenhouse-pilot-readiness.md`
- `LEVER_PILOT_LEDGER_PATH=.promotion-state/evidence/lever-pilot-ledger.jsonl`
- `LEVER_PILOT_READINESS_JSON_PATH=.promotion-state/evidence/lever-pilot-readiness.json`
- `LEVER_PILOT_READINESS_MARKDOWN_PATH=.promotion-state/evidence/lever-pilot-readiness.md`

Read-only campaign inputs are normalized back to the promotion checkout's committed
`evidence/` paths instead of retaining any absolute frozen-checkout location.

## Preparation contract

`prepare` performs all of the following before the lane can become active:

1. requires the frozen checkout HEAD to equal the exact certification revision;
2. refuses tracked modifications in the frozen checkout;
3. fetches `origin/main` without switching the frozen checkout;
4. proves `backend/requirements.txt` exists on both revisions and is byte-identical
   before sharing the existing `.venv`, avoiding a second large dependency install;
5. proves each installed native Termux launcher/pilot/browser contract file exists and
   is byte-identical between frozen and promotion revisions before reusing the native
   commands;
6. refuses an existing promotion worktree whose HEAD no longer equals freshly fetched
   `origin/main` rather than silently running stale promotion code;
7. creates a detached sibling git worktree at exact `origin/main`;
8. creates a WAL-aware SQLite backup using `sqlite3.Connection.backup` and requires
   `PRAGMA quick_check = ok`;
9. requires and canonically validates the frozen Lever Phase B runtime ledger, then
   copies it into isolated promotion state;
10. copies local uploads, handoff files, and any existing Greenhouse runtime ledger
    instead of sharing writable inodes;
11. copies `.env` only into the promotion worktree, rewrites mutable paths, assigns a
    promotion-only browser node, and forces these persistent switches OFF:
    - `ALLOW_REAL_APPLICATION_SUBMIT=false`
    - `ALLOW_REAL_FOLLOWUP_SEND=false`
    - `AUTOPILOT_ENABLED=false`
    - `GREENHOUSE_SUPERVISED_PILOT_ENABLED=false`
    - `LEVER_SUPERVISED_PILOT_ENABLED=false`
12. writes an ignored `backend/.runtime/promotion-lane.json` receipt containing the
    frozen revision, promotion revision, database SHA-256, initial Lever-ledger count
    and digest, isolated-path contract, and fail-safe posture.

An existing verified promotion lane is validated and reused only while it still equals
current `origin/main`. Its database and ledger are never overwritten by an ordinary
prepare.

## Lane switch contract

Before stopping the frozen stack, `start` asks the frozen static-artifact installer to
verify its already-installed exact artifact with zero remote wait. This proves the
rollback path is locally available even though the protected runtime-artifact branch
has advanced to current `main`.

Then it:

1. stops any promotion stack identity and prior promotion Redis identity;
2. stops the frozen stack, its pilot controller, and its native Chromium;
3. archives the shared transient pilot-control directory;
4. starts and clears the isolated promotion Redis broker;
5. starts the promotion worktree with the isolated native runtime directory, Chromium
   profile, database, evidence paths, and broker;
6. requires full Android runtime acceptance;
7. rejects any unexpected pending/active supervised-pilot marker;
8. requires `jobtomatik-pilot status` to prove the fail-safe state.

If promotion Redis startup, stack startup, runtime acceptance, pilot-marker validation,
or fail-safe pilot status fails after the frozen stack was stopped, the helper contains
the promotion runtime and attempts to restart the frozen lane.

## Returning to the frozen lane

`return-frozen` stops the promotion runtime and isolated promotion Redis, archives its
transient pilot-control files, re-verifies the frozen local static artifact, starts the
frozen checkout with the original native browser profile and broker, and runs Android
runtime acceptance.

It never runs `git switch`, `git pull`, `jobtomatik update`, or any database rewrite in
the frozen checkout.

## Installation on the frozen phone

Do not switch or update the frozen checkout. Fetching Git objects is safe because it
does not alter HEAD or the working tree.

From native Termux, install the helper from current `origin/main`:

```bash
proot-distro login ubuntu --shared-tmp -- bash -lc \
  'git -C /root/JobTomatik fetch --no-tags origin main && git -C /root/JobTomatik show origin/main:backend/scripts/jobtomatik_promotion_lane.sh' \
  > "$PREFIX/bin/jobtomatik-promotion"
chmod 700 "$PREFIX/bin/jobtomatik-promotion"
```

The helper requires the existing native `redis-server` and `redis-cli` commands. It
will not replace or reconfigure the frozen Redis service on port 6379.

After the helper's merge commit has a published Android static frontend artifact, the
single command to prepare and enter the isolated lane is:

```bash
jobtomatik-promotion prepare-start
```

Use the browser UI at `http://127.0.0.1:3000`. Do **not** update the frozen APK merely
to enter this lane.

Useful commands:

```bash
jobtomatik-promotion status
jobtomatik-promotion stop
jobtomatik-promotion return-frozen
```

If preparation reports that the frozen Lever runtime ledger is missing or invalid, do
not manufacture a replacement. Preserve the frozen checkout and investigate the
retained Maple evidence path before continuing.

## Submission boundary

The promotion runtime begins fail-safe. Preparing or starting it is not authority to
submit anything.

For each #514 specimen, the ordinary supervised contract still applies separately:

- exact candidate and target revalidation;
- duplicate-identity clearance;
- truthful form fill and retained readback evidence;
- explicit owner approval bound to one exact application/fingerprint/final action;
- one final-submit click maximum;
- no approval replay or silent retry;
- strong employer confirmation evidence;
- independent evidence review before the #514 scoreboard advances.

Maple application 247 remains immutable confirmed evidence and must never be retried.


## September 18 owner quota amendment

The current Lever promotion-evidence quota is **3 genuine confirmed submissions**, not 10.

The current execution run is explicitly **three fresh supervised Lever submissions**. The inherited Maple 247 record remains immutable historical promotion evidence, but it does not reduce this run from three fresh applications to two.

Do not continue collecting supervised certification submissions after the three fresh applications in this run have been completed and reconciled. A failed, expired, or nonqualifying candidate is replaced by another fresh candidate; it does not increase the quota.

All per-application controls remain unchanged: exact target identity, truthful approved payload, exact one-time approval, one final-submit action maximum, strong confirmation evidence, independent review, duplicate prevention, and fail-closed handling of uncertain outcomes.
