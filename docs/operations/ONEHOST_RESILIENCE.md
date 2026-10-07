# OneHost resilience

Bot 5 checks the bookkeeping around production restarts. A restart is not a
submission.

- API restart preserves the application row.
- Worker restart after a consumed approval does not create a duplicate application.
- Browser crash without evidence stays unconfirmed.
- Redis loss does not invent a phantom submission.
- Crash after sufficient confirmation evidence reconciles to confirmed.

Live process killing is not claimed by the unit tests. The production compose
file is checked for restart policies, health probes, and the `/state` volume.
