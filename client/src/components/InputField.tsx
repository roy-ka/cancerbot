import { FormControl, TextField, Button, Grid } from '@mui/material'
import { forwardRef, useImperativeHandle, useRef } from 'react'

export type InputFieldHandle = {
  append: (text: string) => void
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

  useImperativeHandle(ref, () => ({
    append: (text: string) => {
      onChange(value + (value.endsWith(' ') || value === '' ? '' : ' ') + text)
    },
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
      <Grid container spacing={2} sx={{ width: '100%', alignItems: 'flex-end' }}>
        <Grid size={11}>
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
          />
        </Grid>
        <Grid size={1}>
          <Button type="submit" variant="contained" fullWidth>
            🦀 Send
          </Button>
        </Grid>
      </Grid>
    </FormControl>
  )
})

InputField.displayName = 'InputField'
export default InputField
