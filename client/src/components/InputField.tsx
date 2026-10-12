import { FormControl, TextField, IconButton, Button, Box } from '@mui/material'
import { forwardRef, useImperativeHandle, useRef } from 'react'
import { crabReadingSendIcon } from '../assets'

export type InputFieldHandle = {
  append: (text: string) => void
  focus: () => void
}

const InputField = forwardRef<
  InputFieldHandle,
  {
    onSubmit: (e: React.SubmitEvent<HTMLFormElement>) => void
    value: string
    onChange: (value: string) => void
  }
>(({ onSubmit, value, onChange }, ref) => {
  const formRef = useRef<HTMLFormElement>(null)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useImperativeHandle(ref, () => ({
    // No-op when the text is already in the box (e.g. the same source picked twice).
    append: (text: string) => {
      if (value.includes(text.trim())) return
      onChange(value + (value.endsWith(' ') || value === '' ? '' : ' ') + text)
    },
    focus: () => textareaRef.current?.focus(),
  }))

  const handleSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (value.trim() === '') return
    onSubmit(e)
  }

  const handleKeyDown = (e: React.KeyboardEvent<HTMLDivElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      if (value.trim() !== '') formRef.current?.requestSubmit()
    }
  }

  return (
    <FormControl
      component="form"
      ref={formRef}
      onSubmit={handleSubmit}
      sx={{ width: '100%' }}
    >
      <Box sx={{ display: 'flex', alignItems: 'stretch', gap: 1, width: '100%' }}>
        <TextField
          fullWidth
          required
          id="input"
          name="input"
          hiddenLabel
          variant="outlined"
          multiline
          minRows={1}
          maxRows={6}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          value={value}
          inputRef={textareaRef}
        />
        {/* Desktop: icon + text */}
        <Button
          type="submit"
          variant="contained"
          sx={{
            flexShrink: 0,
            borderRadius: 1,
            display: { xs: 'none', sm: 'flex' },
            alignItems: 'center',
            gap: 0.75,
          }}
        >
          <Box component="img" src={crabReadingSendIcon} alt="" sx={{ width: 20, height: 20 }} />
          Send
        </Button>
        {/* Mobile: icon only */}
        <IconButton
          type="submit"
          sx={{
            flexShrink: 0,
            width: 44,
            border: '1px solid rgba(255,255,255,0.25)',
            borderRadius: 1,
            display: { xs: 'flex', sm: 'none' },
          }}
        >
          <Box component="img" src={crabReadingSendIcon} alt="Send" sx={{ width: 24, height: 24 }} />
        </IconButton>
      </Box>
    </FormControl>
  )
})

InputField.displayName = 'InputField'
export default InputField
