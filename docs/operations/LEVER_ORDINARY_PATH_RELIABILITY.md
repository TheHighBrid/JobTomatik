# Lever ordinary-path reliability

Issue #570 stays open until a real ordinary-path run is independently reviewed.
This lane does not hunt for CAPTCHA and does not resurrect the dropped Chromium
campaign.

The supported bookkeeping contract is:

`prepare -> fill -> Answer Vault interruption -> resume the same application ->
another question if needed -> resume -> owner final action -> explicit
confirmation -> evidence persisted -> applied/confirmed -> handoff closed ->
duplicate blocked`

`/thanks` without an explicit success phrase is not confirmation. A changed
Lever posting is not the same application. Missing confirmation becomes
`submission_uncertain`, never `applied`.
