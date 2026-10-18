import assert from 'node:assert/strict'
import test from 'node:test'
import { isSupervisedPilotReviewEligible } from '../src/pilotReviewEligibility.js'

test('only an accepted current review with an approval can enter supervised pilot', () => {
  const approved = {
    decision: 'accepted', valid_for_current_evidence: true,
    approval_reference: 'supervised-consumed-approval',
  }
  assert.equal(isSupervisedPilotReviewEligible(approved), true)
  assert.equal(isSupervisedPilotReviewEligible({ ...approved, approval_reference: null }), false)
  assert.equal(isSupervisedPilotReviewEligible({ ...approved, approval_reference: '   ' }), false)
  assert.equal(isSupervisedPilotReviewEligible({ ...approved, decision: 'rejected' }), false)
  assert.equal(isSupervisedPilotReviewEligible({ ...approved, valid_for_current_evidence: false }), false)
  assert.equal(isSupervisedPilotReviewEligible(null), false)
})
