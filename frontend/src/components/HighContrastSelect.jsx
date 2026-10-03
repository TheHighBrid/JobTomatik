import { Fragment } from 'react'
import { Listbox, ListboxButton, ListboxOption, ListboxOptions } from '@headlessui/react'
import { Check, ChevronDown } from 'lucide-react'

import {
  HIGH_CONTRAST_BUTTON_CLASS,
  HIGH_CONTRAST_OPTION_CLASS,
  HIGH_CONTRAST_OPTIONS_CLASS,
  getHighContrastListboxStyles,
  getHighContrastOptionStyles,
} from './highContrastSelectStyles'

/**
 * Android-safe high-contrast select replacement.
 *
 * Android WebView can ignore CSS applied to native <option> popups. Rendering
 * the menu as regular DOM keeps the JobTomatik design tokens authoritative for
 * every readable state without changing the selected values or policy logic.
 */
export default function HighContrastSelect({
  value,
  onChange,
  options = [],
  className = '',
  disabled = false,
  name,
  'aria-label': ariaLabel,
}) {
  const selectedOption = options.find((option) => option.value === value) || null
  const listboxStyles = getHighContrastListboxStyles()
  const buttonClass = [HIGH_CONTRAST_BUTTON_CLASS, className].filter(Boolean).join(' ')

  return (
    <Listbox value={value} onChange={onChange} disabled={disabled} name={name}>
      <div className="relative w-full">
        <ListboxButton
          className={buttonClass}
          aria-label={ariaLabel}
          style={{ color: listboxStyles.color }}
        >
          <span className="block truncate">{selectedOption?.label || 'Select...'}</span>
          <ChevronDown className="w-4 h-4 flex-shrink-0 opacity-70" aria-hidden="true" />
        </ListboxButton>
        <ListboxOptions
          anchor="bottom start"
          className={HIGH_CONTRAST_OPTIONS_CLASS}
          style={{
            background: listboxStyles.background,
            color: listboxStyles.color,
            borderColor: listboxStyles.borderColor,
            width: 'var(--anchor-width)',
          }}
        >
          {options.map((option) => (
            <ListboxOption key={option.value} value={option.value} as={Fragment}>
              {({ focus, selected }) => (
                <div
                  className={`${HIGH_CONTRAST_OPTION_CLASS} flex items-center justify-between gap-2`}
                  style={getHighContrastOptionStyles({ focus, selected })}
                >
                  <span className={`block truncate ${selected ? 'font-semibold' : 'font-normal'}`}>
                    {option.label}
                  </span>
                  {selected ? <Check className="w-4 h-4 flex-shrink-0" aria-hidden="true" /> : null}
                </div>
              )}
            </ListboxOption>
          ))}
        </ListboxOptions>
      </div>
    </Listbox>
  )
}

export {
  HIGH_CONTRAST_BUTTON_CLASS,
  HIGH_CONTRAST_OPTION_CLASS,
  HIGH_CONTRAST_OPTIONS_CLASS,
  HIGH_CONTRAST_SELECT_TOKENS,
  getHighContrastListboxStyles,
  getHighContrastOptionStyles,
} from './highContrastSelectStyles'
