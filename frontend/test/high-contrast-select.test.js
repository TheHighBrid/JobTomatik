import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import test from 'node:test'

import {
  HIGH_CONTRAST_SELECT_TOKENS,
  getHighContrastListboxStyles,
  getHighContrastOptionStyles,
} from '../src/components/highContrastSelectStyles.js'

const stylesSource = readFileSync(
  new URL('../src/components/highContrastSelectStyles.js', import.meta.url),
  'utf8',
)
const selectSource = readFileSync(
  new URL('../src/components/HighContrastSelect.jsx', import.meta.url),
  'utf8',
)
const vaultSource = readFileSync(
  new URL('../src/components/AnswerPolicyVault.jsx', import.meta.url),
  'utf8',
)
const cssSource = readFileSync(new URL('../src/index.css', import.meta.url), 'utf8')

test('high contrast tokens use JobTomatik design variables', () => {
  const values = Object.values(HIGH_CONTRAST_SELECT_TOKENS)
  for (const token of [
    '--jt-text',
    '--jt-surface',
    '--jt-border',
    '--jt-primary',
    '--jt-primary-soft',
    '--jt-surface-raised',
  ]) {
    assert.equal(
      values.some((value) => String(value).includes(token)),
      true,
      `missing design token ${token}`,
    )
  }
  assert.equal(stylesSource.includes('HIGH_CONTRAST_SELECT_TOKENS'), true)
})

test('option styles always set readable background and text for every state', () => {
  for (const state of [
    {},
    { focus: true },
    { selected: true },
    { focus: true, selected: true },
  ]) {
    const styles = getHighContrastOptionStyles(state)
    assert.equal(typeof styles.background, 'string')
    assert.equal(typeof styles.color, 'string')
    assert.notEqual(styles.background.trim(), '')
    assert.notEqual(styles.color.trim(), '')
    assert.equal(/transparent|inherit|currentColor/i.test(styles.background), false)
    assert.equal(/transparent|inherit/i.test(styles.color), false)
  }
})

test('listbox panel styles use high-contrast surface and text tokens', () => {
  const styles = getHighContrastListboxStyles()
  assert.equal(styles.background, HIGH_CONTRAST_SELECT_TOKENS.surface)
  assert.equal(styles.color, HIGH_CONTRAST_SELECT_TOKENS.text)
  assert.equal(styles.borderColor, HIGH_CONTRAST_SELECT_TOKENS.border)
})

test('HighContrastSelect uses Headless UI Listbox instead of native option elements', () => {
  assert.equal(selectSource.includes("@headlessui/react"), true)
  assert.equal(selectSource.includes('Listbox'), true)
  assert.equal(selectSource.includes('ListboxOptions'), true)
  assert.equal(selectSource.includes('getHighContrastOptionStyles'), true)
  assert.equal(selectSource.includes('<option'), false)
  assert.equal(selectSource.includes('<select'), false)
})

test('AnswerPolicyVault wires HighContrastSelect into Add one policy and related selects', () => {
  assert.equal(vaultSource.includes("import HighContrastSelect from './HighContrastSelect'"), true)
  assert.equal(vaultSource.includes('Application question'), true)
  assert.equal(vaultSource.includes('aria-label="Application question"'), true)
  assert.equal(vaultSource.includes('<HighContrastSelect'), true)
  assert.equal(/<select[\s>]/.test(vaultSource), false)
  assert.equal(vaultSource.includes('<option'), false)
})

test('index.css keeps fortified select option colors as a secondary Android defense', () => {
  assert.equal(cssSource.includes('select option'), true)
  assert.equal(cssSource.includes('color-scheme: dark'), true)
  assert.equal(cssSource.includes('var(--jt-text)'), true)
  assert.equal(cssSource.includes('var(--jt-surface)'), true)
})
