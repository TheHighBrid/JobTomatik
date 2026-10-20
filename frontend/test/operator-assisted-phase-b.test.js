import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const applicationDetail = readFileSync(
  new URL('../src/pages/ApplicationDetail.jsx', import.meta.url),
  'utf8',
)
const operatorPanel = readFileSync(
  new URL('../src/components/OperatorAssistedSubmissionPanel.jsx', import.meta.url),
  'utf8',
)
const finalPanel = readFileSync(
  new URL('../src/components/OperatorFinalSubmitHandoffPanel.jsx', import.meta.url),
  'utf8',
)
const operatorApi = readFileSync(
  new URL('../src/api/operatorAssisted.js', import.meta.url),
  'utf8',
)

test('application detail routes the owner Apply action through JT5 for every target', () => {
  assert.equal(applicationDetail.includes('applyJT5Application'), true)
  assert.equal(applicationDetail.includes('getJT5ApplicationStatus'), true)
  assert.equal(applicationDetail.includes('onClick={() => applyMutation.mutate()}'), true)
  assert.equal(applicationDetail.includes('OperatorAssistedSubmissionPanel'), false)
  assert.equal(applicationDetail.includes('SupervisedSubmissionPanel'), false)
  assert.equal(applicationDetail.includes('SupervisedPilotDossierPanel'), false)
  assert.equal(applicationDetail.includes('submitApplication(id'), false)
  assert.equal(applicationDetail.includes('operatorFinalSubmitReview && (\n        <OperatorFinalSubmitHandoffPanel'), true)
  assert.equal(applicationDetail.includes('ManualHandoffPanel applicationId={Number(id)}'), true)
  assert.equal(applicationDetail.includes('dispatch_status') && applicationDetail.includes('reconciliation_required'), true)
})

test('JT5 client uses the authenticated Apply and status endpoints', () => {
  const apiClient = readFileSync(new URL('../src/api/client.js', import.meta.url), 'utf8')
  assert.equal(apiClient.includes("api.post(`/applications/${id}/jt5/apply`)") , true)
  assert.equal(apiClient.includes("api.get(`/applications/${id}/jt5/status`)") , true)
})

test('operator approval is bound to one exact retained form and typed exact target phrase', () => {
  assert.equal(operatorPanel.includes('handoff_public_id: preflight.operator_handoff_public_id'), true)
  assert.equal(operatorPanel.includes('confirm_operator_final_click: true'), true)
  assert.equal(
    operatorPanel.includes('`SUBMIT ${preflight.employer} | ${preflight.role} | ${preflight.application_url}`'),
    true,
  )
  assert.equal(operatorPanel.includes('preflight.automated_submission_authorized === false'), true)
  assert.equal(operatorPanel.includes('preflight.queue_submission_authorized === false'), true)
  assert.equal(operatorPanel.includes('executionAuthorityOff'), true)
  assert.equal(operatorPanel.includes('Approve exact application & unlock final submit'), true)
})

test('answer-policy review can be revalidated without opening or submitting the employer form', () => {
  assert.equal(
    operatorApi.includes('/manual-reviews/${reviewId}/revalidate-answer-policies'),
    true,
  )
  assert.equal(operatorPanel.includes('revalidateAnswerPolicyReview'), true)
  assert.equal(operatorPanel.includes('Recheck approved answers'), true)
  assert.equal(operatorPanel.includes('This does not open the employer page'), true)
  assert.equal(operatorPanel.includes('create submission approval, queue a worker, or submit anything'), true)
  assert.equal(operatorPanel.includes("'ambiguous_question'"), true)
  assert.equal(operatorPanel.includes("'legal_answer_missing'"), true)
  assert.equal(operatorPanel.includes("'sensitive_answer_missing'"), true)
})

test('answer-policy review UI surfaces remaining retained questions instead of silently clearing them', () => {
  assert.equal(operatorPanel.includes('policyReviewResult?.remaining?.length'), true)
  assert.equal(operatorPanel.includes('policyReviewResult.satisfied_questions'), true)
  assert.equal(operatorPanel.includes('item.canonical_key'), true)
  assert.equal(operatorPanel.includes('item.reason'), true)
  assert.equal(operatorPanel.includes('item.descriptor'), true)
})

test('legacy opaque Lever review recovery is separate and remains fill-only', () => {
  assert.equal(
    operatorApi.includes('/manual-reviews/${reviewId}/retire-stale-for-reprepare'),
    true,
  )
  assert.equal(operatorPanel.includes('retireStaleAnswerPolicyReviewForReprepare'), true)
  assert.equal(operatorPanel.includes('policyReviewResult.fresh_reprepare_available'), true)
  assert.equal(operatorPanel.includes('Retire stale review for fresh fill-only preparation'), true)
  assert.equal(operatorPanel.includes('run a fresh fill-only preparation under the corrected descriptor extractor'), true)
  assert.equal(operatorPanel.includes('Fresh fill-only preparation is now required.'), true)
})

test('legacy encrypted policy can be repaired only by explicit owner re-entry and then rechecked', () => {
  assert.equal(operatorPanel.includes('updateAnswerPolicy'), true)
  assert.equal(operatorPanel.includes("includes('policy_encryption_invalid')"), true)
  assert.equal(operatorPanel.includes('Re-enter the exact answer'), true)
  assert.equal(operatorPanel.includes('Repair answer & recheck'), true)
  assert.equal(operatorPanel.includes('answer_value: cleanAnswer'), true)
  assert.equal(operatorPanel.includes('answer_label: cleanAnswer'), true)
  assert.equal(operatorPanel.includes('fallback_answers: []'), true)
  assert.equal(operatorPanel.includes('allow_autofill: true'), true)
  assert.equal(operatorPanel.includes('confirmed: true'), true)
  assert.equal(operatorPanel.includes('return revalidateAnswerPolicyReview(applicationId, activePolicyReview.id)'), true)
})

test('final retained page exposes bounded owner verification with a separate final action', () => {
  assert.equal(finalPanel.includes('submitOperatorAssistedFinalAction'), true)
  assert.equal(finalPanel.includes('sendHandoffAction'), true)
  assert.equal(finalPanel.includes('cancelHandoff'), false)
  assert.equal(finalPanel.includes("action: 'click'"), true)
  assert.equal(finalPanel.includes("action: 'type'"), false)
  assert.equal(finalPanel.includes('replace_and_submit'), false)
  assert.equal(finalPanel.includes('onClick={handleFrameClick}'), true)
  assert.equal(finalPanel.includes('No typing, answer editing, navigation, arbitrary browser clicks, or automatic retry'), true)
  assert.equal(finalPanel.includes('Submit exact application once'), true)
})

test('final action uses a dedicated once-only API instead of generic handoff actions', () => {
  assert.equal(
    operatorApi.includes('/operator-assisted/handoffs/${handoffPublicId}/submit'),
    true,
  )
  assert.equal(operatorApi.includes('{ lease_token: leaseToken }'), true)
  assert.equal(finalPanel.includes('automatic retry is forbidden'), true)
  assert.equal(finalPanel.includes('Do not submit again; verify the employer page instead.'), true)
})


test('retained final-submit page passively detects employer confirmation after a human click', () => {
  // Before a receipt appears the CAPTCHA interaction must not be interrupted
  // by blind four-second /complete calls holding the handoff row lock.
  assert.equal(finalPanel.includes('|| !capabilities?.confirmation_visible'), true)
  assert.equal(finalPanel.includes('|| (!finalActionStarted && !capabilities?.confirmation_visible)'), false)
  assert.equal(finalPanel.includes('finalActionStarted,\\n    capabilities?.confirmation_visible,'), false)
  assert.equal(finalPanel.includes('passiveConfirmationCheck'), true)
  assert.equal(finalPanel.includes('verifyRetainedConfirmation'), true)
  assert.equal(finalPanel.includes('window.setInterval(verifyRetainedConfirmation, 4000)'), true)
  assert.equal(finalPanel.includes('await completeHandoff(session.public_id, leaseToken)'), true)
  assert.equal(
    finalPanel.includes('Employer confirmation detected automatically. Application evidence is being finalized.'),
    true,
  )
  assert.equal(finalPanel.includes('if ([403, 410].includes(status))'), true)
  assert.equal(finalPanel.includes('409 means the exact retained page is still pre-submit'), true)
})
