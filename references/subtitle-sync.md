# Sentence-Level Subtitle Sync (no SRT file needed)

A lightweight technique for syncing subtitles to audio when you have **full narration text but no timestamped subtitle file** (no SRT/VTT). Uses character-length-weighted time estimation to approximate sentence boundaries during playback.

## The Technique

```
1. Split narration into sentences (regex: /[^.!?\n]+[.!?]+/g)
2. On audio loadedmetadata → compute character-weighted time windows
3. On audio timeupdate → find which sentence the current time falls in
4. Update subtitle text to that sentence
```

## Implementation

### 1. Build segments from narration text

```javascript
function buildSubtitleSegments(narration) {
  if (!narration) { subtitleSegments = []; return; }
  const sentenceRegex = /[^.!?\n]+[.!?]+/g;
  const matches = narration.match(sentenceRegex);
  if (!matches || matches.length <= 1) {
    // Single sentence or unparseable — show the full text (no truncation)
    subtitleSegments = [{ text: narration.trim(), start: 0, end: Infinity }];
    return;
  }
  subtitleSegments = matches.map(s => ({ text: s.trim(), charLen: s.trim().length }));
}
```

### 2. Weight segments by character length

Longer sentences take longer to speak. Weight proportionally:

```javascript
function timeweightSubtitleSegments(duration) {
  if (!duration || duration <= 0 || subtitleSegments.length === 0) return;
  const totalChars = subtitleSegments.reduce((sum, s) => sum + s.charLen, 0);
  let cursor = 0;
  for (const seg of subtitleSegments) {
    const fraction = seg.charLen / totalChars;
    seg.start = cursor;
    seg.end = cursor + fraction * duration;
    cursor = seg.end;
  }
}
```

### 3. Sync on timeupdate

```javascript
function updateSubtitleFromTime(currentTime) {
  const subEl = document.getElementById('player-subtitles');
  if (!subEl || subtitleSegments.length === 0) return;
  let text = '';
  for (const seg of subtitleSegments) {
    if (currentTime >= seg.start && currentTime < seg.end) {
      text = seg.text;
      break;
    }
  }
  // Past the last segment — hold final sentence
  if (!text && subtitleSegments.length > 0) {
    text = subtitleSegments[subtitleSegments.length - 1].text;
  }
  subEl.textContent = text;
}

// Wire up — guard with CC toggle so subtitlesOnly visible state is respected
document.getElementById('player-audio').addEventListener('timeupdate', () => {
  if (!state.subtitlesOn) return;
  updateSubtitleFromTime(document.getElementById('player-audio').currentTime);
});
```

### 4. Reset on scene/track change

```javascript
// In updatePlayer():
buildSubtitleSegments(newNarration);
// Show first sentence immediately
subEl.textContent = subtitleSegments[0]?.text || '';

// Compute timing once audio metadata loads
const onMeta = () => {
  timeweightSubtitleSegments(audioEl.duration);
  audioEl.removeEventListener('loadedmetadata', onMeta);
};
audioEl.addEventListener('loadedmetadata', onMeta);
```

## Edge Cases

- **Single sentence**: Just show it all (`start: 0, end: Infinity`)
- **No matching sentences** (e.g., no punctuation): fall back to showing the full text (no truncation — the overlay's `max-height: 115px` with `-webkit-line-clamp: 3` handles visual overflow)
- **Audio never loads metadata**: segments stay un-timed (start/end never get assigned), but the first sentence still shows. The `timeupdate` handler will run but won't match any segment, so the first sentence stays visible — acceptable degradation
- **Past all segments**: hold the last sentence so the subtitle doesn't disappear before the scene ends
- **User toggles CC mid-playback**: immediately call `updateSubtitleFromTime(audio.currentTime)` to sync to the right sentence — otherwise the subtitle text stays at whatever the last `timeupdate` event set before CC was off
- **Audio not yet loaded when CC toggled on**: if `audio.currentTime` is 0, `updateSubtitleFromTime(0)` will show the first sentence, which is the correct default

## Why not equal division?

Simple `sentenceIndex / totalSentences * duration` works for uniform narration but falls apart when sentences vary wildly in length:

> "No." (2 chars, short pause)
> "The ancient citadel of Korvosa, with its towering spires of black obsidian and streets paved in memories of a thousand years, stood as the last bastion against the encroaching darkness." (200 chars, takes 6 seconds to speak)

Equal division would give both ~0.5 seconds. Character-weighting gives the long sentence ~85% of the audio duration, which matches how TTS actually reads them.

## Limitations

- **No word-level precision**: This estimates sentence boundaries, doesn't highlight individual words. For perfect sync, generate SRT files during TTS creation.
- **Pauses/pacing**: Natural speaker pauses between sentences or dramatic silence aren't modeled. A 0.5s fade between segments would help but isn't implemented here.
- **TTS speed variation**: If the TTS engine reads at a variable speed (slow on long words, fast on punctuation), the weighting skews slightly but is still better than equal division.
