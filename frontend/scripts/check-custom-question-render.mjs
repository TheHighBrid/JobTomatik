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
  const render = (component, props) => renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(component, props)))
  const html = render(Form, { initialQuestion: 'Which office?', initialCompany: 'Test Company', recheck: true, availableOptions: [{ label: 'Ottawa', value: 'ottawa' }] })
  assert.ok(html.includes('Save answer and recheck'))
  assert.ok(html.includes('Which office?'))
  assert.ok(html.includes('Test Company'))
  assert.ok(html.includes('Ottawa'))
  assert.ok(!/type="checkbox"[^>]*checked/.test(html))
  const policy = { id: 3, canonical_key: customPolicyKey('Which office?'), match_phrases: ['Which office?', 'Preferred office?'], answer_value: 'Ottawa', scope: 'company', scope_value: 'Test Company', mode: 'answer', is_active: true }
  client.setQueryData(['answer-policy-catalog'], { data: [] })
  client.setQueryData(['answer-policies'], { data: [policy] })
  const Vault = (await server.ssrLoadModule('/src/components/AnswerPolicyVault.jsx')).default
  const vault = render(Vault)
  assert.ok(vault.includes('Add a custom question'))
  assert.ok(vault.includes('Edit question and answer'))
  assert.ok(vault.includes('Which office?'))
  const edited = render(Form, { policy })
  assert.ok(edited.includes('Preferred office?'))
  assert.ok(edited.includes('Ottawa'))
  console.log('Rendered React checks: vault integration, readable saved question, edit form, scoped recheck form, employer options, and default authorization state passed.')
} finally { await server.close() }
