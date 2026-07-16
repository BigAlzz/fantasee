#!/usr/bin/env python3
"""
Subtitle Generator — align narration text to TTS audio using Whisper word timestamps

Produces per-sentence subtitle segments with real timestamps instead of
character-length estimation. Run this once per TTS audio file to generate
a .subs.json sidecar file.

Usage:
    python generate_subtitles.py tts_rampart_s01.mp3 \
        --text "High on the walls..." \
        --output siege_scene01.subs.json
"""

import argparse
import difflib
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional

from faster_whisper import WhisperModel


# ── Config ──────────────────────────────────────────────────────────────
MODEL_SIZE = "base"  # Small enough for CPU, accurate enough for clean TTS
_whisper_model = None  # Cache the model to avoid reloading per scene


def _get_whisper_model() -> WhisperModel:
    """Get or create the Whisper model singleton."""
    global _whisper_model
    if _whisper_model is None:
        _whisper_model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return _whisper_model


def _generate_subtitles_word_aligned(audio_path: str, narration_text: str) -> list[dict]:
    """Align script sentences to Whisper word timestamps."""
    sentence_re = re.compile(r'[^.!?\n]+[.!?]+|[^.!?\n]+$')
    sentences = [s.strip() for s in sentence_re.findall(narration_text) if s.strip()]
    if not sentences:
        sentences = [narration_text.strip()]

    print(f"  Narration: {len(sentences)} sentences", file=sys.stderr)
    print(f"  Transcribing {audio_path}...", file=sys.stderr)
    model = _get_whisper_model()
    whisper_segments, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=200),
    )
    if info.language != "en":
        print(
            f"  WARNING: detected language {info.language} "
            f"(p={info.language_probability:.2f})",
            file=sys.stderr,
        )

    def norm_word(word: str) -> str:
        return re.sub(r"[^a-z0-9']+", "", word.lower()).strip("'")

    def script_words(text: str) -> list[str]:
        words = []
        for raw in re.findall(r"[A-Za-z0-9']+", text):
            norm = norm_word(raw)
            if norm:
                words.append(norm)
        return words

    whisper_words = []
    for seg in whisper_segments:
        for word in getattr(seg, "words", None) or []:
            raw = getattr(word, "word", "") or ""
            norm = norm_word(raw)
            start = getattr(word, "start", None)
            end = getattr(word, "end", None)
            if norm and start is not None and end is not None:
                whisper_words.append({
                    "word": norm,
                    "start": float(start),
                    "end": float(end),
                })

    print(f"  Whisper: {len(whisper_words)} words", file=sys.stderr)
    if not whisper_words:
        print("  WARNING: no speech words detected!", file=sys.stderr)
        return [{"text": s, "start": 0, "end": 0} for s in sentences]

    recognized_tokens = [w["word"] for w in whisper_words]
    audio_end = max(w["end"] for w in whisper_words)
    total_chars = sum(max(1, len(s)) for s in sentences)

    def estimated_range(sentence_idx: int) -> tuple[float, float]:
        before = sum(max(1, len(s)) for s in sentences[:sentence_idx])
        this = max(1, len(sentences[sentence_idx]))
        start = audio_end * (before / total_chars) if total_chars else 0.0
        end = audio_end * ((before + this) / total_chars) if total_chars else audio_end
        return start, max(end, start + 0.5)

    segments = []
    search_from = 0
    for sent_idx, sentence in enumerate(sentences):
        words = script_words(sentence)
        if words:
            target_len = len(words)
            best_score = -1.0
            best_start = search_from
            best_end = min(len(recognized_tokens), search_from + max(1, target_len))
            max_scan = min(len(recognized_tokens), search_from + max(40, target_len * 5))
            for start_idx in range(search_from, max_scan):
                min_len = max(1, target_len - max(2, target_len // 3))
                max_len = target_len + max(3, target_len // 3)
                for win_len in range(min_len, max_len + 1):
                    end_idx = min(len(recognized_tokens), start_idx + win_len)
                    if end_idx <= start_idx:
                        continue
                    candidate = recognized_tokens[start_idx:end_idx]
                    score = difflib.SequenceMatcher(None, words, candidate, autojunk=False).ratio()
                    if score > best_score:
                        best_score = score
                        best_start = start_idx
                        best_end = end_idx
                if best_score >= 0.92:
                    break
            if best_score >= 0.25 and best_end > best_start:
                start = whisper_words[best_start]["start"]
                end = whisper_words[best_end - 1]["end"]
                search_from = max(best_end, best_start + 1)
            else:
                start, end = estimated_range(sent_idx)
        else:
            start, end = estimated_range(sent_idx)
        segments.append({
            "text": sentence,
            "start": round(max(0.0, start), 3),
            "end": round(max(start + 0.35, end), 3),
        })

    for i in range(len(segments) - 1):
        next_start = segments[i + 1]["start"]
        if segments[i]["end"] > next_start:
            segments[i]["end"] = round(max(segments[i]["start"] + 0.25, next_start), 3)
        if segments[i + 1]["start"] < segments[i]["end"]:
            segments[i + 1]["start"] = round(segments[i]["end"], 3)
        if segments[i + 1]["end"] <= segments[i + 1]["start"]:
            segments[i + 1]["end"] = round(segments[i + 1]["start"] + 0.35, 3)
    for seg in segments:
        seg["start"] = round(min(max(0.0, seg["start"]), audio_end), 3)
        seg["end"] = round(min(max(seg["end"], seg["start"] + 0.25), audio_end + 0.5), 3)

    print(f"  Generated {len(segments)} subtitle segments", file=sys.stderr)
    for seg in segments:
        dur = seg["end"] - seg["start"]
        preview = seg["text"][:60].replace("\n", " ")
        print(f"    [{seg['start']:.2f}s-{seg['end']:.2f}s] ({dur:.2f}s) {preview}...", file=sys.stderr)
    return segments





def generate_subtitles(
    audio_path: str,
    narration_text: str,
) -> list[dict]:
    """
    Full pipeline: transcribe audio with Whisper, align its segments to
    the known narration text, return real subtitle segments with timestamps.

    Strategy: Whisper naturally segments at pauses (sentence boundaries).
    We group Whisper's segments into the known narration sentences by
    using difflib on the full transcript, then map Whisper's own
    segment timestamps to each sentence.

    Each output segment has {text, start, end} in seconds.
    """
    return _generate_subtitles_word_aligned(audio_path, narration_text)

    # Split narration into sentences
    sentence_re = re.compile(r'[^.!?\n]+[.!?]+|[^.!?\n]+$')
    sentences = [
        s.strip()
        for s in sentence_re.findall(narration_text)
        if s.strip()
    ]
    if not sentences:
        sentences = [narration_text.strip()]

    print(f"  Narration: {len(sentences)} sentences", file=sys.stderr)

    # Transcribe with Whisper
    print(f"  Transcribing {audio_path}...", file=sys.stderr)
    model = _get_whisper_model()
    whisper_segments, info = model.transcribe(
        audio_path,
        word_timestamps=True,
        language="en",
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=200),
    )
    if info.language != "en":
        print(f"  WARNING: detected language {info.language} "
              f"(p={info.language_probability:.2f})", file=sys.stderr)

    # Collect Whisper segments with their timestamps and full text
    ws_segs = []
    for seg in whisper_segments:
        text = seg.text.strip()
        if text:
            ws_segs.append({"text": text, "start": seg.start, "end": seg.end})

    print(f"  Whisper: {len(ws_segs)} segments", file=sys.stderr)

    if not ws_segs:
        print(f"  WARNING: no speech detected!", file=sys.stderr)
        return [{"text": s, "start": 0, "end": 0} for s in sentences]

    # ── Match known sentences to Whisper segments ──
    # For each known sentence, find the Whisper segment with the most
    # word overlap. Group consecutive sentences that map to the same
    # segment and distribute the segment's time among them.

    def _clean(text: str) -> set[str]:
        """Lowercase word set for comparison."""
        return set(re.sub(r'[^\w\s\']', ' ', text.lower()).split())

    sent_sigs = [_clean(s) for s in sentences]
    ws_sigs = [_clean(s["text"]) for s in ws_segs]

    # Best-matching segment index for each sentence
    sent_to_seg = []
    for ss in sent_sigs:
        best_score, best_idx = -1, 0
        for wi, ws in enumerate(ws_sigs):
            if ss:
                overlap = len(ss & ws)
                if overlap > best_score:
                    best_score, best_idx = overlap, wi
        sent_to_seg.append(best_idx)

    # Enforce monotonic segment alignment: known sentences are spoken in
    # order, so segment indices must never decrease. When a short sentence
    # matches a segment earlier in the audio, clamp it forward to maintain
    # temporal consistency.
    for i in range(1, len(sent_to_seg)):
        if sent_to_seg[i] < sent_to_seg[i - 1]:
            sent_to_seg[i] = sent_to_seg[i - 1]

    # Build output: walk through sentences, create groups of consecutive
    # sentences that map to the same segment, emit each group with
    # proportionally distributed time.
    segments = []
    si = 0
    while si < len(sentences):
        cur_seg = sent_to_seg[si]
        # Find where the run ends
        run_end = si + 1
        while run_end < len(sentences) and sent_to_seg[run_end] == cur_seg:
            run_end += 1

        group = sentences[si:run_end]
        seg_ws = ws_segs[cur_seg]
        seg_start, seg_end = seg_ws["start"], seg_ws["end"]

        if len(group) == 1:
            segments.append({"text": group[0], "start": seg_start, "end": seg_end})
        else:
            total_chars = sum(len(s) for s in group)
            if total_chars == 0:
                total_chars = len(group)
            cursor = seg_start
            for gs in group:
                frac = len(gs) / total_chars
                chunk = (seg_end - seg_start) * frac
                end = cursor + chunk if gs != group[-1] else seg_end
                segments.append({"text": gs, "start": cursor, "end": end})
                cursor += chunk

        si = run_end

    # ── Post-process ──
    # 1. Fix non-monotonic segments (start > end)
    # 2. Assign minimum duration
    # 3. Fix overlaps and enforce monotonicity

    for seg in segments:
        if seg["start"] > seg["end"]:
            seg["start"], seg["end"] = seg["end"], seg["start"]

    # Minimum display time: 0.05s per character, floor 0.5s
    for i, seg in enumerate(segments):
        dur = seg["end"] - seg["start"]
        if dur < 0.3:
            # Assign a minimum duration proportional to text
            min_dur = max(0.5, len(seg["text"]) * 0.05)
            # Borrow time from the gap before the NEXT segment
            if i + 1 < len(segments):
                gap = segments[i + 1]["start"] - seg["start"]
                if gap > min_dur:
                    seg["end"] = seg["start"] + min_dur
                elif gap > 0:
                    seg["end"] = seg["start"] + gap
                else:
                    seg["end"] = seg["start"] + min_dur
            else:
                # Last segment — borrow from start
                if i > 0:
                    seg["start"] = max(0, segments[i - 1]["end"])
                    seg["end"] = seg["start"] + min_dur
                else:
                    seg["end"] = seg["start"] + min_dur

    # Fix overlaps
    for i in range(len(segments) - 1):
        if segments[i]["end"] > segments[i + 1]["start"]:
            midpoint = (segments[i]["end"] + segments[i + 1]["start"]) / 2
            segments[i]["end"] = midpoint
            segments[i + 1]["start"] = midpoint
        elif segments[i + 1]["start"] > segments[i]["end"] + 0.5:
            midpoint = (segments[i]["end"] + segments[i + 1]["start"]) / 2
            segments[i]["end"] = midpoint
            segments[i + 1]["start"] = midpoint

    # Monotonicity
    for i in range(1, len(segments)):
        if segments[i]["start"] < segments[i - 1]["end"]:
            segments[i]["start"] = segments[i - 1]["end"]

    print(f"  Generated {len(segments)} subtitle segments", file=sys.stderr)
    for i, seg in enumerate(segments):
        dur = seg["end"] - seg["start"]
        preview = seg["text"][:60].replace("\n", " ")
        print(f"    [{seg['start']:.2f}s-{seg['end']:.2f}s] ({dur:.2f}s) {preview}...", file=sys.stderr)

    return segments


def process_scene(
    scene_key: str,
    narration_dir: Path,
    output_dir: Path,
    tts_prefix: str = "rampart",
):
    """Generate subtitles for one scene and save to output_dir."""
    # Find narration text
    n_candidates = [
        narration_dir / f"narration_{scene_key}.txt",
    ]
    # Also try zero-padded for single-digit keys
    if re.match(r"^\d$", scene_key):
        n_candidates.append(narration_dir / f"narration_0{scene_key}.txt")

    narration_text = None
    n_path = None
    for nc in n_candidates:
        if nc.exists():
            narration_text = nc.read_text(encoding="utf-8").strip()
            n_path = nc
            break

    if not narration_text:
        print(f"  SKIP: narration file not found for scene {scene_key}")
        return False

    # Find TTS audio
    # Try various filename patterns
    audio_path = None
    candidates = [
        output_dir / f"tts_{tts_prefix}_s{scene_key}.mp3",
        output_dir / f"tts_{tts_prefix}_s0{scene_key}.mp3",
    ]
    for ap in candidates:
        if ap.exists():
            audio_path = ap
            break
    if not audio_path:
        print(f"  SKIP: TTS audio not found for scene {scene_key}")
        return False

    # Generate subtitles
    print(f"\n=== Scene {scene_key} ===")
    segments = generate_subtitles(
        str(audio_path),
        narration_text,
    )

    # Save
    sub_path = output_dir / f"subs_{tts_prefix}_s{scene_key}.json"
    with open(sub_path, "w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2)
    print(f"  Saved: {sub_path}")

    return True


def main():
    parser = argparse.ArgumentParser(description="Generate subtitle segments from TTS + narration")
    parser.add_argument("audio", nargs="?", help="Single TTS audio file path")
    parser.add_argument("--text", help="Narration text (for single mode)")
    parser.add_argument("--output", help="Output JSON path (for single mode)")
    args = parser.parse_args()

    if args.audio:
        if not args.text:
            parser.error("--text required for single-file mode")
        segments = generate_subtitles(args.audio, args.text)
        output_path = args.output or (Path(args.audio).with_suffix(".subs.json"))
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(segments, f, indent=2)
        print(f"Saved {len(segments)} segments to {output_path}")
        # Print as JSON lines for easy viewing
        print(json.dumps(segments, indent=2))

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
