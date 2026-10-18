import assert from 'node:assert/strict'
import test from 'node:test'
import isSupervisedPilotReviewEligible from '../src/pilotReviewEligibility.js'

const approved = {
  decision: 'accepted', valid_for_current_evidence: true,
  approval_reference: 'supervised-consumed-approval',
}

test('only an accepted current review with an approval can enter supervised pilot', () =>
  assert.deepEqual([
    isSupervisedPilotReviewEligible(approved),
    isSupervisedPilotReviewEligible({ ...approved, approval_reference: null }),
    isSupervisedPilotReviewEligible({ ...approved, approval_reference: '   ' }),
    isSupervisedPilotReviewEligible({ ...approved, decision: 'rejected' }),
    isSupervisedPilotReviewEligible({ ...approved, valid_for_current_evidence: false }),
    isSupervisedPilotReviewEligible(null),
  ], [true, false, false, false, false, false]))
