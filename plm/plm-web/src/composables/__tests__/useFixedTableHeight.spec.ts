import { describe, expect, it } from 'vitest'

import { resolveFixedTableHeight } from '../useFixedTableHeight'

describe('resolveFixedTableHeight', () => {
  it('uses the available viewport height when it is within the configured bounds', () => {
    expect(resolveFixedTableHeight({ viewportHeight: 900, reservedHeight: 320 })).toBe(580)
  })

  it('keeps the table usable when page controls leave too little space', () => {
    expect(resolveFixedTableHeight({ viewportHeight: 700, reservedHeight: 520 })).toBe(320)
  })

  it('does not let a large viewport produce an unbounded list', () => {
    expect(resolveFixedTableHeight({ viewportHeight: 1800, reservedHeight: 200 })).toBe(760)
  })
})
