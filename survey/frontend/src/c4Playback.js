// Native seeking must not count a skipped clip as a complete listen.
export function hasCompletePlayback(played, duration, tolerance = 0.05) {
  if (!played?.length || !Number.isFinite(duration) || duration <= 0) return false
  const allowedGap = Math.min(tolerance, duration * 0.02)
  let end = 0
  for (let index = 0; index < played.length; index++) {
    if (played.start(index) > end + allowedGap) return false
    end = Math.max(end, played.end(index))
  }
  return end >= duration - allowedGap
}
