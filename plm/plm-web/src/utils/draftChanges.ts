/** A receipt only acknowledges submitted cells; newer edits keep their metadata and rebase. */
export function acknowledgeDraftChanges<Value, Change extends { before: Value | null; after: Value | null }>(
  changes: Map<string, Change>,
  submitted: readonly { field: string; after: Value | null }[] | undefined,
  saved: Readonly<Record<string, Value | null | undefined>> | null,
  equal: (left: Value | null, right: Value | null) => boolean
) {
  const accepted = (field: string, fallback: Value | null): Value | null =>
    saved && Object.prototype.hasOwnProperty.call(saved, field) ? saved[field] ?? null : fallback
  const sent = submitted ?? [...changes].map(([field, change]) => ({ field, after: accepted(field, change.after) }))
  for (const cell of sent) {
    const pending = changes.get(cell.field)
    if (!pending) continue
    if (equal(pending.after, cell.after)) changes.delete(cell.field)
    else pending.before = accepted(cell.field, cell.after)
  }
}
