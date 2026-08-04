import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

const evidenceMaterialsSource = readFileSync(
  new URL('../src/pages/EvidenceMaterials.jsx', import.meta.url),
  'utf8',
)
const dossierSource = readFileSync(
  new URL('../src/components/SupervisedPilotDossierPanel.jsx', import.meta.url),
  'utf8',
)
const applicationDetailSource = readFileSync(
  new URL('../src/pages/ApplicationDetail.jsx', import.meta.url),
  'utf8',
)

test('verified materials workspace honors and synchronizes exact application selection', () => {
  assert.equal(evidenceMaterialsSource.includes('useSearchParams'), true)
  assert.equal(
    evidenceMaterialsSource.includes("searchParams.get('application')"),
    true,
  )
  assert.equal(evidenceMaterialsSource.includes('applications.some('), true)
  assert.equal(
    evidenceMaterialsSource.includes(
      "nextParams.set('application', nextApplicationId)",
    ),
    true,
  )
  assert.equal(
    evidenceMaterialsSource.includes(
      'setSearchParams(nextParams, { replace: true })',
    ),
    true,
  )
  assert.equal(
    evidenceMaterialsSource.includes('onChange={handleApplicationChange}'),
    true,
  )
})

test('dossier and detail route to the exact application materials workspace', () => {
  assert.equal(
    dossierSource.includes(
      'to={`/evidence-materials?application=${applicationId}`}',
    ),
    true,
  )
  assert.equal(
    applicationDetailSource.includes(
      'to={`/evidence-materials?application=${id}`}',
    ),
    true,
  )
})

test('application detail uses source-backed verified-material language', () => {
  assert.equal(
    applicationDetailSource.includes('Generate Verified Cover Letter'),
    true,
  )
  assert.equal(
    applicationDetailSource.includes('Build source-backed materials'),
    true,
  )
  assert.equal(
    applicationDetailSource.includes(
      'insufficient evidence will route to review',
    ),
    true,
  )
  assert.equal(applicationDetailSource.includes('Generate one with AI'), false)
})
