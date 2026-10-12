import { afterEach, describe, expect, it, vi } from 'vitest'

import { formatFileSize, saveBlob } from '../file'

describe('file utilities', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('formats file sizes for business tables', () => {
    expect(formatFileSize(0)).toBe('0 B')
    expect(formatFileSize(1024)).toBe('1 KB')
    expect(formatFileSize(1536)).toBe('1.5 KB')
    expect(formatFileSize(1024 * 1024)).toBe('1 MB')
  })

  it('downloads a Blob and releases the object URL', () => {
    const createObjectURL = vi.spyOn(URL, 'createObjectURL').mockReturnValue('blob:m4')
    const revokeObjectURL = vi.spyOn(URL, 'revokeObjectURL').mockImplementation(() => undefined)
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => undefined)
    const blob = new Blob(['M4'])

    saveBlob(blob, 'M4.txt')

    expect(createObjectURL).toHaveBeenCalledWith(blob)
    expect(click).toHaveBeenCalledOnce()
    expect(revokeObjectURL).toHaveBeenCalledWith('blob:m4')
  })
})
