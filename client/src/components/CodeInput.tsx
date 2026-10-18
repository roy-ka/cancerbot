import { useEffect, useRef } from 'react'
import { Box } from '@mui/material'

export const CODE_LENGTH = 6

type CodeInputProps = {
  value: string
  onChange: (value: string) => void
  onComplete?: (value: string) => void
  disabled?: boolean
  error?: boolean
  autoFocus?: boolean
}

/**
 * Six single-digit boxes for the emailed sign-in code. Typing moves to the
 * next box, Backspace on an empty box goes back, and pasting (or a phone's
 * one-time-code autofill, which arrives as one multi-character input) fills
 * every box at once. `value` is the digits entered so far, left-aligned.
 */
export default function CodeInput({ value, onChange, onComplete, disabled, error, autoFocus }: CodeInputProps) {
  const inputs = useRef<Array<HTMLInputElement | null>>([])
  // The handlers read the digits from here, not from `value`: keystrokes and
  // focus events can arrive before React re-renders with the last change, and
  // a stale `value` made the gap check in onFocus pull focus back to box 1
  // mid-typing. update() writes it synchronously; the effect picks up
  // changes made by the parent (e.g. clearing after a wrong code).
  const current = useRef(value)
  useEffect(() => {
    current.current = value
  }, [value])

  const update = (next: string) => {
    current.current = next
    onChange(next)
  }

  useEffect(() => {
    if (autoFocus) inputs.current[0]?.focus()
  }, [autoFocus])

  // Cleared from outside (wrong code, new code requested): start over at box 1.
  useEffect(() => {
    if (value === '' && !disabled) inputs.current[0]?.focus()
  }, [value, disabled])

  const focusBox = (i: number) => {
    const box = inputs.current[Math.max(0, Math.min(CODE_LENGTH - 1, i))]
    box?.focus()
    box?.select()
  }

  const setDigits = (next: string, focusIndex: number) => {
    const digits = next.replace(/\D/g, '').slice(0, CODE_LENGTH)
    update(digits)
    if (digits.length === CODE_LENGTH) {
      inputs.current[CODE_LENGTH - 1]?.blur()
      onComplete?.(digits)
    } else {
      focusBox(focusIndex)
    }
  }

  const handleInput = (i: number, raw: string) => {
    let typed = raw.replace(/\D/g, '')
    if (!typed) return
    const value = current.current
    // Typing into a filled box whose digit wasn't selected yields old+new.
    const old = value[i]
    if (old && typed.length === 2 && typed.includes(old)) {
      typed = typed.startsWith(old) ? typed[1] : typed[0]
    }
    // Several digits at once means paste or autofill: fill from this box on.
    const next = value.slice(0, i) + typed + value.slice(i + typed.length)
    setDigits(next, i + typed.length)
  }

  const handleKeyDown = (i: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Backspace') {
      e.preventDefault()
      const value = current.current
      if (value[i]) {
        update(value.slice(0, i) + value.slice(i + 1))
        focusBox(i)
      } else if (i > 0) {
        update(value.slice(0, i - 1) + value.slice(i))
        focusBox(i - 1)
      }
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      focusBox(i - 1)
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      focusBox(i + 1)
    }
  }

  const handlePaste = (i: number, e: React.ClipboardEvent<HTMLInputElement>) => {
    e.preventDefault()
    handleInput(i, e.clipboardData.getData('text'))
  }

  return (
    <Box
      role="group"
      aria-label="6-digit code"
      sx={{ display: 'flex', justifyContent: 'center', gap: { xs: 0.75, sm: 1.25 } }}
    >
      {Array.from({ length: CODE_LENGTH }, (_, i) => (
        <Box
          key={i}
          component="input"
          ref={(el: HTMLInputElement | null) => {
            inputs.current[i] = el
          }}
          value={value[i] ?? ''}
          onChange={(e: React.ChangeEvent<HTMLInputElement>) => handleInput(i, e.target.value)}
          onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => handleKeyDown(i, e)}
          onPaste={(e: React.ClipboardEvent<HTMLInputElement>) => handlePaste(i, e)}
          onFocus={(e: React.FocusEvent<HTMLInputElement>) => {
            // Digits are kept left-aligned, so never leave a gap before this box.
            if (i > current.current.length) focusBox(current.current.length)
            else e.target.select()
          }}
          disabled={disabled}
          inputMode="numeric"
          pattern="[0-9]*"
          // Only the first box advertises one-time-code, so a phone's autofill
          // lands there and handleInput spreads it across all six.
          autoComplete={i === 0 ? 'one-time-code' : 'off'}
          aria-label={`Digit ${i + 1}`}
          data-testid={`code-digit-${i}`}
          sx={{
            width: { xs: 40, sm: 48 },
            height: { xs: 52, sm: 60 },
            textAlign: 'center',
            fontSize: { xs: '1.4rem', sm: '1.6rem' },
            fontWeight: 700,
            fontFamily: 'inherit',
            color: 'rgba(255,255,255,0.95)',
            bgcolor: 'rgba(255,255,255,0.06)',
            border: '1px solid',
            borderColor: error ? 'error.main' : 'rgba(255,255,255,0.2)',
            borderRadius: '8px',
            outline: 'none',
            caretColor: 'transparent',
            transition: 'border-color 0.15s ease, box-shadow 0.15s ease',
            '&:focus': {
              borderColor: error ? 'error.main' : 'rgba(124, 92, 255, 0.9)',
              boxShadow: '0 0 0 3px rgba(124, 92, 255, 0.25)',
            },
            '&:disabled': { opacity: 0.5 },
          }}
        />
      ))}
    </Box>
  )
}
