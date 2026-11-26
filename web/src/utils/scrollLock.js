/**
 * Single-axis scroll locking & horizontal week-column snapping helpers for WeekView.
 */

/**
 * Determine intended scroll axis from initial pointer delta.
 * Returns null while within deadzone (< threshold), otherwise 'x' or 'y'.
 */
export function resolveScrollAxis(dx, dy, threshold = 6) {
  const dist = Math.hypot(dx, dy)
  if (!Number.isFinite(dist) || dist < threshold) return null
  return Math.abs(dx) >= Math.abs(dy) ? 'x' : 'y'
}

/**
 * Project final horizontal scrollLeft aligned cleanly to an integer column boundary.
 * Note: positive touch velocity (finger dragging right) scrolls left (smaller scrollLeft).
 */
export function projectColumnSnap(currentLeft, velocityPxPerMs, colWidth, maxCols) {
  if (!Number.isFinite(colWidth) || colWidth <= 0) return Math.max(0, Math.round(currentLeft || 0))
  const safeMaxCols = Math.max(7, Math.floor(maxCols || 7))
  const maxColIdx = Math.max(0, safeMaxCols - 7)
  const projectedLeft = (Number(currentLeft) || 0) - (Number(velocityPxPerMs) || 0) * 160
  const targetCol = Math.max(0, Math.min(maxColIdx, Math.round(projectedLeft / colWidth)))
  return Math.round(targetCol * colWidth)
}
