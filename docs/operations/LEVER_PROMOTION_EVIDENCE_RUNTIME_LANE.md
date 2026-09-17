# Lever Promotion Evidence Runtime Lane

Date: 2026-09-17

Tracking: #514

## Purpose

The completed September Phase B objective sprint remains frozen at certification
revision `198b197dfcece6fbf9f3edfc5a92511fd951b484`. Real supervised submissions
needed for the separate Lever maturity gate must not mutate that checkout, its SQLite
database, its native Chromium profile, or its retained objective history.

`backend/scripts/jobtomatik_promotion_lane.sh` creates a second, isolated execution
lane for new promotion evidence while preserving the frozen lane as a rollback target.

This helper does **not** arm the supervised pilot, issue an application approval,
queue an application, click final Submit, or enable any persistent submit/autopilot
flag.

## Isolation model

The promotion lane uses:

- source-of-truth frozen checkout: `/root/JobTomatik` at exact revision `198b197d...`;
- current-main sibling worktree: `/root/JobTomatik-promotion`;
- promotion database: `backend/jobtomatik-promotion.db`;
- promotion native runtime state: `~/.jobtomatik-promotion-runtime`;
- promotion Chromium profile: `~/.jobtomatik-promotion-chromium`;
- the standard localhost API/frontend/CDP ports, but only after the frozen stack has
  been stopped;
- the standard pilot-control `/tmp` bus, with its transient files archived between
  lane switches so no request is replayed across lanes.

Only one lane is active at a time.

## Preparation contract

`prepare` performs all of the following before creating the worktree:

1. requires the frozen checkout HEAD to equal the exact certification revision;
2. refuses tracked modifications in the frozen checkout;
3. fetches `origin/main` without switching the frozen checkout;
4. proves `backend/requirements.txt` is byte-identical before sharing the existing
   `.venv`, avoiding a second large dependency installation;
5. proves the native Termux launcher/pilot/browser scripts are byte-identical between
   frozen and promotion revisions before reusing the installed native commands;
6. creates a detached sibling git worktree at exact `origin/main`;
7. creates a WAL-aware SQLite backup using `sqlite3.Connection.backup` and requires
   `PRAGMA quick_check = ok`;
8. copies local uploads/handoff files instead of sharing writable inodes;
9. copies `.env` only into the promotion worktree and forces these persistent switches
   OFF:
   - `ALLOW_REAL_APPLICATION_SUBMIT=false`
   - `ALLOW_REAL_FOLLOWUP_SEND=false`
   - `AUTOPILOT_ENABLED=false`
   - `GREENHOUSE_SUPERVISED_PILOT_ENABLED=false`
   - `LEVER_SUPERVISED_PILOT_ENABLED=false`
10. writes an ignored `backend/.runtime/promotion-lane.json` receipt containing the
    frozen revision, promotion revision, database SHA-256, and fail-safe posture.

An existing verified promotion lane is validated and reused. Its database is never
overwritten by an ordinary prepare.

## Lane switch contract

Before stopping the frozen stack, `start` asks the frozen static-artifact installer to
verify its already-installed exact artifact with zero remote wait. This proves the
rollback path is locally available even though the protected runtime-artifact branch
has advanced to current `main`.

Then it:

1. stops any promotion stack identity;
2. stops the frozen stack, its pilot controller, and its native Chromium;
3. archives the shared transient pilot-control directory;
4. starts the promotion worktree with the isolated native runtime directory and
   Chromium profile;
5. requires full Android runtime acceptance;
6. rejects any unexpected pending/active supervised-pilot marker;
7. requires `jobtomatik-pilot status` to prove the fail-safe state.

If promotion startup or acceptance fails, the helper contains the promotion runtime and
attempts to restart the frozen lane.

## Returning to the frozen lane

`return-frozen` stops the promotion runtime, archives its transient pilot-control files,
re-verifies the frozen local static artifact, starts the frozen checkout with the
original native browser profile, and runs Android runtime acceptance.

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
