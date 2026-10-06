# GH-OH1 preflight

`jobtomatik greenhouse preflight <application>` is the mechanical gate before a
supervised OneHost Greenhouse execution. It is not a submit command and it does
not issue final-submit authority.

A ready report looks like:

```
GH-OH1 PREFLIGHT
Target identity       PASS
Applicant dossier     PASS
Resume binding        PASS
Answer policies       PASS
Duplicate check       PASS
OneHost health        PASS
Browser affinity      PASS
Evidence storage      PASS
Kill switch           PASS
Final submit authority CLOSED

READY FOR SUPERVISED EXECUTION
```

`CLOSED` is the success state for final-submit authority. An enabled live-submit
or Greenhouse pilot flag fails the preflight. The command does not click submit,
create an approval, or promote application state.

Live probes fail closed unless OneHost readiness, the worker health URL, the
OneHost browser profile, evidence storage, and `AUTOMATION_GLOBAL_KILL_SWITCH`
are actually verified. Missing private material is a blocker, not a bypass.
