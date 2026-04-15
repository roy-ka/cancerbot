import { FormControl, TextField, Button, Grid } from '@mui/material'
import { forwardRef, useImperativeHandle } from 'react'

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

  return (
    <FormControl
      component="form"
      onSubmit={handleSubmit}
      sx={{ width: '100%' }}
    >
      <Grid container spacing={2} sx={{ width: '100%' }}>
        <Grid size={11}>
          <TextField
            fullWidth
            required
            id="input"
            name="input"
            hiddenLabel
            type="input"
            variant="outlined"
            onChange={(e) => onChange(e.target.value)}
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
