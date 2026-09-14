import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createServer } from 'vite'

const root = fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, server: { middlewareMode: true }, appType: 'custom' })
try {
  const Panel = (await server.ssrLoadModule('/src/components/OperatorAssistedSubmissionPanel.jsx')).default
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  client.setQueryData(['operator-assisted-preflight', 1], { data: {
    platform: 'lever', ready: false, blockers: ['open_manual_review'],
    automated_submission_authorized: false, queue_submission_authorized: false,
    employer: 'Synthetic Company', role: 'Test Role', application_url: 'https://example.test/apply',
  } })
  client.setQueryData(['supervised-approvals', 1], { data: [] })
  const error = 'No next-step or final-submit control was found.'
  const review = {
    id: 2, status: 'open', reason_code: 'unsupported_control',
    answer_policy_question_count: 0, application_step_blockers: [error],
  }
  const render = (reviews) => renderToStaticMarkup(React.createElement(
    QueryClientProvider, { client }, React.createElement(Panel, { application: { id: 1, manual_reviews: reviews } }),
  ))
  const blocked = render([review])
  assert.ok(blocked.includes(error))
  assert.ok(blocked.includes('Application step needs attention'))
  assert.ok(!blocked.includes('Recheck approved answers'))
  assert.ok(!blocked.includes('Retire stale review'))
  assert.ok(!blocked.includes('custom.unclassified'))
  const mixed = render([{ ...review, answer_policy_question_count: 1 }])
  assert.ok(mixed.includes(error))
  assert.ok(mixed.includes('Recheck approved answers'))
  const question = render([{ ...review, answer_policy_question_count: 1, application_step_blockers: [] }])
  assert.ok(question.includes('Recheck approved answers'))
  assert.ok(!question.includes('Application step needs attention'))
  console.log('Rendered application-step reviews: original error visible, no question/refill action, mixed and genuine question reviews preserved.')
} finally {
  await server.close()
}
