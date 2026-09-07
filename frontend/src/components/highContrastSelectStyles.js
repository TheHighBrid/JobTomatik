/** Design-token-backed styles for Android-safe high-contrast custom selects. */

export const HIGH_CONTRAST_SELECT_TOKENS = Object.freeze({
  text: 'var(--jt-text)',
  textSoft: 'var(--jt-text-soft)',
  surface: 'var(--jt-surface)',
  surfaceRaised: 'var(--jt-surface-raised)',
  border: 'var(--jt-border)',
  borderStrong: 'var(--jt-border-strong)',
  primary: 'var(--jt-primary)',
  primarySoft: 'var(--jt-primary-soft)',
  muted: 'var(--jt-muted)',
})

/** Button class aligned with `.input w-full` visual weight. */
export const HIGH_CONTRAST_BUTTON_CLASS =
  'input w-full flex items-center justify-between gap-2 text-left cursor-pointer'

export const HIGH_CONTRAST_OPTIONS_CLASS =
  'z-50 max-h-60 overflow-auto rounded-[var(--jt-radius-sm)] border py-1 shadow-lg outline-none [--anchor-gap:4px]'

export const HIGH_CONTRAST_OPTION_CLASS =
  'cursor-pointer select-none px-3.5 py-2.5 text-sm outline-none'

/**
 * Resolve option listbox styles for a given interaction state.
 * Always returns explicit background + text colors from design tokens so
 * Android WebView never falls back to unreadable native <option> colors.
 */
export function getHighContrastOptionStyles({ focus = false, selected = false } = {}) {
  if (selected && focus) {
    return {
      background: HIGH_CONTRAST_SELECT_TOKENS.primary,
      color: '#ffffff',
    }
  }
  if (selected) {
    return {
      background: HIGH_CONTRAST_SELECT_TOKENS.primarySoft,
      color: HIGH_CONTRAST_SELECT_TOKENS.text,
    }
  }
  if (focus) {
    return {
      background: HIGH_CONTRAST_SELECT_TOKENS.surfaceRaised,
      color: HIGH_CONTRAST_SELECT_TOKENS.text,
    }
  }
  return {
    background: HIGH_CONTRAST_SELECT_TOKENS.surface,
    color: HIGH_CONTRAST_SELECT_TOKENS.text,
  }
}

/** Panel chrome for the floating options listbox. */
export function getHighContrastListboxStyles() {
  return {
    background: HIGH_CONTRAST_SELECT_TOKENS.surface,
    color: HIGH_CONTRAST_SELECT_TOKENS.text,
    borderColor: HIGH_CONTRAST_SELECT_TOKENS.border,
  }
}
