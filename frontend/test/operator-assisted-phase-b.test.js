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

test('Lever application detail uses the operator-assisted lane instead of automated live submit', () => {
  assert.equal(applicationDetail.includes('OperatorAssistedSubmissionPanel'), true)
  assert.equal(applicationDetail.includes("supervisedPlatform === 'lever'"), true)
  assert.equal(
    applicationDetail.includes("supervisedPlatform !== 'lever' && (\n        <SupervisedSubmissionPanel"),
    true,
  )
  assert.equal(
    applicationDetail.includes("!applicationFinished && supervisedPlatform !== 'lever' && (\n            <button"),
    true,
  )
  assert.equal(applicationDetail.includes('global live-submit, the Lever automated pilot, and autopilot stay off'), true)
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

test('final retained page exposes no generic browser mutation surface', () => {
  assert.equal(finalPanel.includes('submitOperatorAssistedFinalAction'), true)
  assert.equal(finalPanel.includes('sendHandoffAction'), false)
  assert.equal(finalPanel.includes('cancelHandoff'), false)
  assert.equal(finalPanel.includes("action: 'click'"), false)
  assert.equal(finalPanel.includes("action: 'type'"), false)
  assert.equal(finalPanel.includes('replace_and_submit'), false)
  assert.equal(finalPanel.includes('onClick={handleFrameClick}'), false)
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
