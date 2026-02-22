import { FormControl, TextField, Button, Grid } from '@mui/material'
import { useState } from 'react'

export default function InputField({
  onSubmit,
}: {
  onSubmit: (e: React.SubmitEvent<HTMLFormElement>) => void
}) {
  const [input, setInput] = useState<string>('')

  const handleSubmit = (e: React.SubmitEvent<HTMLFormElement>) => {
    e.preventDefault()
    if (input.trim() === '') return
    onSubmit(e)
    setInput('')
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
            onChange={(e) => setInput(e.target.value)}
            value={input}
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
}
