import assert from 'node:assert/strict'
import { test } from 'node:test'
import { hasCompletePlayback } from '../src/c4Playback.js'

const ranges = entries => ({ length: entries.length, start: i => entries[i][0], end: i => entries[i][1] })

test('full native playback credits a completed clip', () => {
  assert.equal(hasCompletePlayback(ranges([[0, 3]]), 3), true)
  assert.equal(hasCompletePlayback(ranges([[0, 2.98]]), 3), true)
})

test('seeking to the end without listening to the middle is not completion', () => {
  assert.equal(hasCompletePlayback(ranges([[0, 0.3], [2.9, 3]]), 3), false)
  assert.equal(hasCompletePlayback(ranges([[2.8, 3]]), 3), false)
  assert.equal(hasCompletePlayback(ranges([[0, 1.5]]), 3), false)
})

test('pauses retain contiguous listening coverage', () => {
  assert.equal(hasCompletePlayback(ranges([[0, 1.1], [1.12, 3]]), 3), true)
  assert.equal(hasCompletePlayback(ranges([[0, 1.1], [1.2, 3]]), 3), false)
})

test('unloaded or invalid media never completes', () => {
  for (const duration of [0, NaN, Infinity, -1]) assert.equal(hasCompletePlayback(ranges([[0, 3]]), duration), false)
  assert.equal(hasCompletePlayback(ranges([]), 3), false)
  assert.equal(hasCompletePlayback(null, 3), false)
})
