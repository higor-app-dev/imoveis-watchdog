# Concatenating Playwright Test Videos with ffmpeg

Playwright's `video: "on"` config records a `video.webm` per test. When you have
19+ tests, sending individual files is impractical. This reference covers
combining them into one file.

## Pre-Flight: Verify Codec Uniformity

All files must share the same codec, resolution, and pixel format. Playwright
(v1.61+) records VP8, 800×450, yuv420p by default — but verify:

```bash
ffprobe -v error -select_streams v:0 \
  -show_entries stream=codec_name,width,height,pix_fmt \
  "$f" 2>/dev/null
```

If parameters match across all files, use the concat demuxer (zero re-encode
cost). If they differ, you must re-encode to a common intermediate format first.

## Build the File List

Playwright names directories by test description (with Unicode). Sort by path
for a sensible chapter order:

```bash
find test-results -name "video.webm" -type f | sort > /tmp/video_list.txt
```

## Concatenate with `-c copy` (no re-encode)

```bash
ffmpeg -f concat -safe 0 -i /tmp/video_list.txt \
  -c copy -y compiled-test-run.webm
```

**Flags explained:**
- `-f concat` — concat demuxer (requires identical codec parameters)
- `-safe 0` — allow absolute paths in the file list
- `-c copy` — stream copy, no re-encode (lossless, instant)

## Produce an MP4 for Telegram/Discord

WebM is less supported on mobile messaging apps. Convert the compiled video:

```bash
ffmpeg -i compiled-test-run.webm \
  -c:v libx264 -preset fast -crf 23 -pix_fmt yuv420p \
  -y compiled-test-run.mp4
```

**Flags:**
- `-preset fast` — speed/compression balance; use `veryfast` for quicker
  encodes at the cost of file size
- `-crf 23` — default quality (18=visually lossless, 28=smaller/lower)
- `-pix_fmt yuv420p` — required for H.264 in most players

## Typical Output

19 Playwright tests (each 2–8 seconds) → ~44s of video → ~1.2MB WebM / ~850KB
H.264 MP4.

## Cleanup

```bash
rm /tmp/video_list.txt
```

The `test-results/` directory is already in `.gitignore` so these artifacts
don't pollute the repo.

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| `Packet mismatch` | Streams have slightly different codec params | Drop `-c copy`, let ffmpeg re-encode: remove `-c copy` |
| `Non-monotonous DTS` | Timestamps out of order | Add `-fflags +genpts` before output |
| Black frames at start | Playwright video includes blank header | Use `-ss 0.2` to skip the first 200ms |
| Audio sync drift | WebM has audio stream (usually silence) | Add `-an` to drop audio, or `-c:a copy` to keep it |
