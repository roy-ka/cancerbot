import { describe, it, expect } from 'vitest'
import {
  jsonType,
  flattenFields,
  learnSchema,
  validate,
  normalizeEndpoint,
  newEndpointSchema,
  LEARN_THRESHOLD,
  type EndpointSchema,
} from './schema'

describe('jsonType', () => {
  it('distinguishes null, array, and object from primitives', () => {
    expect(jsonType(null)).toBe('null')
    expect(jsonType([1, 2])).toBe('array')
    expect(jsonType({})).toBe('object')
    expect(jsonType('x')).toBe('string')
    expect(jsonType(3)).toBe('number')
    expect(jsonType(true)).toBe('boolean')
  })
})

describe('flattenFields', () => {
  it('walks nested objects into dot-paths', () => {
    const fields = flattenFields({ conversation: { id: 'c1', title: 'T' }, ok: true })
    expect(fields).toMatchObject({
      conversation: 'object',
      'conversation.id': 'string',
      'conversation.title': 'string',
      ok: 'boolean',
    })
  })

  it('records arrays and recurses their first element under []', () => {
    const fields = flattenFields({ messages: [{ role: 'user', hidden: false }] })
    expect(fields['messages']).toBe('array')
    expect(fields['messages[].role']).toBe('string')
    expect(fields['messages[].hidden']).toBe('boolean')
  })

  it('ignores empty arrays (nothing to sample)', () => {
    const fields = flattenFields({ items: [] })
    expect(fields['items']).toBe('array')
    expect(Object.keys(fields)).toEqual(['items'])
  })
})

function learnN(schema: EndpointSchema, body: unknown, n: number) {
  for (let i = 0; i < n; i++) learnSchema(schema, body)
}

describe('learnSchema', () => {
  it('counts samples and per-field presence', () => {
    const s = newEndpointSchema()
    learnSchema(s, { a: 1, b: 'x' })
    learnSchema(s, { a: 2 }) // b absent this time
    expect(s.sampleCount).toBe(2)
    expect(s.fields['a'].seen).toBe(2)
    expect(s.fields['b'].seen).toBe(1) // seen stays; sampleCount grew → lower confidence
    expect(s.fields['a'].types).toEqual({ number: 2 })
  })
})

describe('validate', () => {
  it('flags a required field (>=95%) that goes missing', () => {
    const s = newEndpointSchema()
    learnN(s, { id: '1', name: 'n' }, LEARN_THRESHOLD) // both present 100%
    const v = validate(s, { id: '2' }, 'GET /x')
    expect(v).toHaveLength(1)
    expect(v[0]).toMatchObject({ kind: 'missing_required', path: 'name' })
  })

  it('does NOT flag a low-confidence field that is missing', () => {
    const s = newEndpointSchema()
    learnN(s, { id: '1' }, 19) // id 100%
    learnSchema(s, { id: '1', maybe: 'here' }) // maybe seen 1/20 = 5%
    const v = validate(s, { id: '2' }, 'GET /x')
    expect(v.find((x) => x.path === 'maybe')).toBeUndefined()
  })

  it('flags a changed concrete type', () => {
    const s = newEndpointSchema()
    learnN(s, { count: 5 }, LEARN_THRESHOLD)
    const v = validate(s, { count: '5' }, 'GET /x')
    expect(v).toHaveLength(1)
    expect(v[0]).toMatchObject({ kind: 'type_changed', path: 'count' })
    expect(v[0].detail).toContain('expected number')
  })

  it('does NOT treat null as a type change for a nullable field', () => {
    const s = newEndpointSchema()
    learnN(s, { note: 'hi' }, LEARN_THRESHOLD)
    const v = validate(s, { note: null }, 'GET /x')
    expect(v).toHaveLength(0)
  })

  it('flags an unknown field (drift)', () => {
    const s = newEndpointSchema()
    learnN(s, { id: '1' }, LEARN_THRESHOLD)
    const v = validate(s, { id: '2', surprise: 'new' }, 'GET /x')
    expect(v).toHaveLength(1)
    expect(v[0]).toMatchObject({ kind: 'unknown_field', path: 'surprise' })
  })

  it('returns no violations for a matching response', () => {
    const s = newEndpointSchema()
    learnN(s, { id: '1', tags: ['a'] }, LEARN_THRESHOLD)
    expect(validate(s, { id: '2', tags: ['b', 'c'] }, 'GET /x')).toEqual([])
  })
})

describe('normalizeEndpoint', () => {
  it('templates out UUID path segments', () => {
    expect(
      normalizeEndpoint('GET', 'http://x/conversations/2aacf1c0-231a-4672-9dda-398974c05945/messages/'),
    ).toBe('GET /conversations/:id/messages/')
  })

  it('templates out numeric ids and strips the query string', () => {
    expect(normalizeEndpoint('post', 'http://x/items/42?page=3')).toBe('POST /items/:id')
  })

  it('leaves static paths untouched', () => {
    expect(normalizeEndpoint('GET', 'http://x/auth/check/')).toBe('GET /auth/check/')
  })
})
