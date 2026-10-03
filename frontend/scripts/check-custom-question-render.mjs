import assert from 'node:assert/strict'
import { fileURLToPath } from 'node:url'
import React from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createServer } from 'vite'
const root = fileURLToPath(new URL('../', import.meta.url))
const server = await createServer({ root, server: { middlewareMode: true }, appType: 'custom' })
try {
  const Form = (await server.ssrLoadModule('/src/components/CustomQuestionPolicyForm.jsx')).default
  const { customPolicyKey } = await server.ssrLoadModule('/src/customQuestionPolicies.js')
  const client = new QueryClient()
  const renderComponentMarkup = (component, props) => renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(component, props)))
  const formMarkup = renderComponentMarkup(Form, { initialQuestion: 'Which office?', initialCompany: 'Test Company', recheck: true, availableOptions: [{ label: 'Ottawa', value: 'ottawa' }] })
  assert.ok(formMarkup.includes('Save answer and recheck'))
  assert.ok(formMarkup.includes('Which office?'))
  assert.ok(formMarkup.includes('Test Company'))
  assert.ok(formMarkup.includes('Ottawa'))
  assert.ok(formMarkup.includes('type="checkbox"'))
  assert.ok(!formMarkup.includes('checked=""'))
  const policy = { id: 3, canonical_key: customPolicyKey('Which office?'), match_phrases: ['Which office?', 'Preferred office?'], answer_value: 'Ottawa', scope: 'company', scope_value: 'Test Company', mode: 'answer', is_active: true }
  client.setQueryData(['answer-policy-catalog'], { data: [] })
  client.setQueryData(['answer-policies'], { data: [policy] })
  const Vault = (await server.ssrLoadModule('/src/components/AnswerPolicyVault.jsx')).default
  const vaultMarkup = renderComponentMarkup(Vault)
  assert.ok(vaultMarkup.includes('Add a custom question'))
  assert.ok(vaultMarkup.includes('Edit question and answer'))
  assert.ok(vaultMarkup.includes('Which office?'))
  const editedMarkup = renderComponentMarkup(Form, { policy })
  assert.ok(editedMarkup.includes('Preferred office?'))
  assert.ok(editedMarkup.includes('Ottawa'))
  console.log('Rendered React checks: vault integration, readable saved question, edit form, scoped recheck form, employer options, and default authorization state passed.')
} finally { await server.close() }
