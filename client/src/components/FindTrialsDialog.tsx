import { useEffect, useState } from 'react'
import {
  Alert,
  Autocomplete,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import TravelExploreIcon from '@mui/icons-material/TravelExplore'
import {
  buildTrialSearchUrl,
  canSearchTrials,
  countRecruitingStudies,
  filterCountries,
  suggestCityCorrections,
} from '../utils/trialSearch'
import { TRIAL_COUNTRIES } from '../utils/trialCountries'

/** Debounce before asking CT.gov, so typing a city isn't one request per key. */
const COUNT_DEBOUNCE_MS = 450

type CountState =
  | { status: 'idle' }
  /** A city is being typed — not yet checkable, see committedCity. */
  | { status: 'typing' }
  | { status: 'loading' }
  | { status: 'done'; count: number }
  | { status: 'unknown' }

/**
 * Opt-in "find trials I could join" flow. Collects a condition and a coarse
 * location, then opens ClinicalTrials.gov's own recruiting search.
 *
 * Nothing is prefilled from the conversation on purpose: guessing the user's
 * condition from chat text would be an assumption about their diagnosis, which
 * is exactly the wrong thing to get subtly wrong here.
 *
 * `variant`:
 *  - "icon"  — compact icon button for the sidebar header
 *  - "chip"  — inline chip for the new-conversation intro
 */
export default function FindTrialsDialog({
  variant = 'icon',
}: {
  variant?: 'icon' | 'chip'
}) {
  const [open, setOpen] = useState(false)
  const [condition, setCondition] = useState('')
  const [country, setCountry] = useState<string | null>(null)
  const [city, setCity] = useState('')
  // The city text the user has finished entering (committed on blur or Enter).
  // Checking mid-keystroke cannot work: CT.gov's location search matches whole
  // terms only, so every partial city — 'Tel A' on the way to 'Tel Aviv' —
  // legitimately returns zero and would be reported as a misspelling.
  const [committedCity, setCommittedCity] = useState('')
  // Stored with the query it belongs to, so a result is never shown against
  // input it wasn't computed for.
  const [result, setResult] = useState<{ key: string; state: CountState } | null>(null)
  // "Did you mean" suggestions, also keyed to the query they were computed for.
  const [suggestions, setSuggestions] = useState<{ key: string; cities: string[] } | null>(null)

  const handleClose = () => {
    setOpen(false)
    setCondition('')
    setCountry(null)
    setCity('')
    setCommittedCity('')
    setResult(null)
    setSuggestions(null)
  }

  const countries = country ? [country] : []
  const ready = canSearchTrials({ condition, countries, city })

  const trimmedCity = city.trim()
  const countryKey = country ?? ''
  const queryKey = JSON.stringify([trimmedCity, countryKey, condition.trim()])
  // Only ask about a city the user has actually finished typing.
  const shouldCheck = Boolean(committedCity) && committedCity === trimmedCity

  // Ask CT.gov what it has for that city, so an unknown or misspelt place is
  // visible before the user leaves the app. Re-runs when the condition or
  // countries change, since the count is only meaningful for the whole query.
  useEffect(() => {
    if (!shouldCheck) return
    const controller = new AbortController()
    const timer = setTimeout(async () => {
      const n = await countRecruitingStudies(
        {
          condition,
          city: committedCity,
          countries: countryKey ? [countryKey] : [],
        },
        controller.signal,
      )
      if (controller.signal.aborted) return
      // null means the request failed — not evidence of zero
      setResult({
        key: queryKey,
        state: n === null ? { status: 'unknown' } : { status: 'done', count: n },
      })
    }, COUNT_DEBOUNCE_MS)

    return () => {
      clearTimeout(timer)
      controller.abort()
    }
  }, [shouldCheck, committedCity, countryKey, condition, queryKey])

  // Derived rather than stored: assigning this in the effect would both trip the
  // set-state-in-effect rule and briefly show a previous city's count against
  // newly typed text. 'typing' covers a city still being entered — there is
  // nothing truthful to say about a partial name.
  const count: CountState = !trimmedCity
    ? { status: 'idle' }
    : !shouldCheck
      ? { status: 'typing' }
      : result?.key === queryKey
        ? result.state
        : { status: 'loading' }

  const isZeroResult = count.status === 'done' && count.count === 0

  // When the exact check comes back empty, ask CT.gov for the closest city
  // names it actually has in that country — a "did you mean", not a full
  // picklist (see suggestCityCorrections for why a full list was rejected).
  // Needs a country: the sample this draws suggestions from is scoped to one.
  useEffect(() => {
    if (!isZeroResult || !country) return
    const controller = new AbortController()
    suggestCityCorrections(country, committedCity, controller.signal).then((cities) => {
      if (controller.signal.aborted) return
      setSuggestions({ key: queryKey, cities })
    })
    return () => controller.abort()
  }, [isZeroResult, country, committedCity, queryKey])

  const citySuggestions = suggestions?.key === queryKey ? suggestions.cities : []

  /** Treat the city as final, so it can be checked. */
  const commitCity = () => setCommittedCity(trimmedCity)

  /** Adopt a suggested spelling and re-check it immediately. */
  const pickSuggestion = (name: string) => {
    setCity(name)
    setCommittedCity(name)
  }

  const handleSearch = () => {
    if (!ready) return
    // Built and opened client-side — the condition/city/countries never reach
    // the CancerBot backend and are never stored.
    window.open(
      buildTrialSearchUrl({ condition, countries, city }),
      '_blank',
      'noopener,noreferrer',
    )
    handleClose()
  }

  const label = 'Find trials to join'

  const trigger =
    variant === 'chip' ? (
      <Chip
        icon={<TravelExploreIcon />}
        label={label}
        data-testid="find-trials-trigger"
        onClick={() => setOpen(true)}
        variant="outlined"
        sx={{
          cursor: 'pointer',
          color: 'rgba(255,255,255,0.85)',
          borderColor: 'rgba(255,255,255,0.25)',
          '&:hover': { borderColor: 'primary.main' },
        }}
      />
    ) : (
      <Tooltip title={label}>
        <IconButton
          size="small"
          aria-label={label}
          data-testid="find-trials-trigger"
          onClick={() => setOpen(true)}
          sx={{ color: 'rgba(255,255,255,0.6)' }}
        >
          <TravelExploreIcon fontSize="small" />
        </IconButton>
      </Tooltip>
    )

  return (
    <>
      {trigger}

      <Dialog
        open={open}
        onClose={handleClose}
        fullWidth
        maxWidth="sm"
        slotProps={{
          backdrop: { sx: { backgroundColor: 'rgba(0,0,0,0.3)' } },
        }}
      >
        <DialogTitle>Find clinical trials to join</DialogTitle>
        <DialogContent
          sx={{ display: 'flex', flexDirection: 'column', gap: 2, pt: 1 }}
        >
          <Alert severity="info" data-testid="find-trials-disclaimer">
            This opens the official ClinicalTrials.gov search for trials that are
            currently recruiting. CancerBot does not screen eligibility or
            recommend trials — discuss any trial with your care team.
          </Alert>

          <TextField
            label="Condition"
            fullWidth
            value={condition}
            onChange={(e) => setCondition(e.target.value)}
            placeholder="e.g. glioblastoma, breast cancer"
            slotProps={{ htmlInput: { 'data-testid': 'find-trials-condition' } }}
          />
          <Autocomplete
            options={TRIAL_COUNTRIES as unknown as string[]}
            value={country}
            onChange={(_, value) => setCountry(value)}
            // Single choice on purpose: a multi-select's option panel can sit
            // on top of the dialog's own action buttons once several countries
            // are picked, since it stays open (disableCloseOnSelect) to allow
            // adding more. One country avoids that entirely — the popup closes
            // as soon as the choice is made, which is also just simpler to use.
            // buildTrialSearchUrl still accepts several, so a multi-country
            // search remains a query-string builder capability if ever needed
            // again — just not one this dialog exposes.
            // MUI's default substring filter buries Israel under Afghanistan,
            // Pakistan and Tajikistan when you type 'is'
            filterOptions={(options, { inputValue }) =>
              filterCountries(options, inputValue)
            }
            slotProps={{
              // The theme's background.paper is rgba(255,255,255,0.06) — nearly
              // transparent — so without an explicit colour the option list
              // renders over whatever is behind the dialog. Opaque, matching the
              // account Menu in ConversationList.
              paper: {
                sx: {
                  backgroundColor: 'rgb(18,25,45)',
                  backgroundImage: 'none',
                  border: '1px solid rgba(255,255,255,0.1)',
                  borderRadius: 2,
                },
              },
            }}
            renderInput={(params) => (
              <TextField
                {...params}
                label="Country"
                placeholder="e.g. Israel"
                slotProps={{
                  htmlInput: {
                    ...params.inputProps,
                    'data-testid': 'find-trials-country',
                  },
                }}
              />
            )}
          />

          <TextField
            label="City (optional)"
            fullWidth
            value={city}
            onChange={(e) => setCity(e.target.value)}
            onBlur={commitCity}
            onKeyDown={(e) => {
              if (e.key === 'Enter') commitCity()
            }}
            placeholder="e.g. Tel Aviv"
            helperText={
              <Typography
                component="span"
                variant="caption"
                data-testid="find-trials-city-count"
                sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}
              >
                {count.status === 'typing' &&
                  'Checked once you finish typing — press Enter or click away'}
                {count.status === 'loading' && (
                  <>
                    <CircularProgress size={11} />
                    Checking ClinicalTrials.gov…
                  </>
                )}
                {count.status === 'done' &&
                  (count.count > 0
                    ? `${count.count.toLocaleString()} recruiting ${
                        count.count === 1 ? 'study' : 'studies'
                      } found`
                    : 'ClinicalTrials.gov lists no recruiting studies there — check the spelling, or search anyway')}
                {count.status === 'unknown' &&
                  "Couldn't reach ClinicalTrials.gov to check this"}
                {count.status === 'idle' &&
                  'Optional — ClinicalTrials.gov has no city list to pick from'}
              </Typography>
            }
            slotProps={{ htmlInput: { 'data-testid': 'find-trials-city' } }}
          />

          {isZeroResult && citySuggestions.length > 0 && (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                flexWrap: 'wrap',
                gap: 1,
                mt: -1,
              }}
            >
              <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.5)' }}>
                Did you mean:
              </Typography>
              {citySuggestions.map((name) => (
                <Chip
                  key={name}
                  label={name}
                  size="small"
                  data-testid="find-trials-city-suggestion"
                  onClick={() => pickSuggestion(name)}
                  variant="outlined"
                  sx={{
                    cursor: 'pointer',
                    color: 'rgba(255,255,255,0.85)',
                    borderColor: 'rgba(255,255,255,0.25)',
                    '&:hover': { borderColor: 'primary.main' },
                  }}
                />
              ))}
            </Box>
          )}

          <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.5)' }}>
            No precise location is used — a country, optionally narrowed to a
            city, is enough. What you enter is sent only to ClinicalTrials.gov,
            to check the city and to open the search; CancerBot does not store it.
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleClose}>Cancel</Button>
          <Button
            onClick={handleSearch}
            variant="contained"
            disabled={!ready}
            data-testid="find-trials-submit"
          >
            Search ClinicalTrials.gov
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}
