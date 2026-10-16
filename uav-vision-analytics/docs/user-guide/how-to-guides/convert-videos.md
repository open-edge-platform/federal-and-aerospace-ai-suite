<!--
SPDX-FileCopyrightText: (C) 2026 Intel Corporation
SPDX-License-Identifier: Apache-2.0
-->

# Use Your Own Videos

The pipelines loop `.avi` sample files from `resources/videos/`. To run the application on your own footage,
convert it into that format with `scripts/convert_video.sh`. It accepts any input that ffmpeg can read
(`.mp4`, `.mov`, `.mkv`, `.avi`, `.ts`, `.webm`, ...).

## Which file goes where

| File | Used by pipelines |
| --- | --- |
| `resources/videos/uav_sample_front.avi` | CPU |
| `resources/videos/uav_sample_back.avi` | NPU |
| `resources/videos/uav_sample_bottom.avi` | GPU |

## Prerequisites

Docker, or `ffmpeg` and `ffprobe` on the host. The script uses host `ffmpeg` when it is installed and otherwise
runs ffmpeg from the DL Streamer Pipeline Server image named in `.env`, so no extra install is needed.

## Steps

1. **Convert the file.** From the application root, for example for the CPU (front) camera:

   ```bash
   ./scripts/convert_video.sh /path/to/my_clip.mp4 -o resources/videos/uav_sample_front.avi -f
   ```

   `-f` overwrites an existing output. Without `-o`, the script writes `<name>.avi` next to the input
   (`<name>_converted.avi` if the input is already an `.avi`).

2. **Use the same length for every camera.** If you replace more than one file, give them all the same frame count so
   their loops stay in step. Pick a number no larger than the shortest clip provides at 30 fps (a multiple of 250 keeps the
   loop point on a keyframe):

   ```bash
   ./scripts/convert_video.sh front.mp4  -o resources/videos/uav_sample_front.avi  -n 1750 -f
   ./scripts/convert_video.sh back.mov   -o resources/videos/uav_sample_back.avi   -n 1750 -f
   ./scripts/convert_video.sh bottom.mkv -o resources/videos/uav_sample_bottom.avi -n 1750 -f
   ```

3. **Check the result.** The script verifies the output and prints a summary, ending with
   `Verified: valid H.264/AVI, starts on a keyframe, decodes without errors.` It exits with an error
   if any check fails.

4. **Restart the pipelines** so they read the new files:

   ```bash
   ./scripts/uav_pipeline_control.sh stop all
   ./scripts/uav_pipeline_control.sh start all --h264
   ```

## What the script produces

H.264 (High profile, yuv420p) in an AVI container, 30 fps, no audio, about 4 Mbps, with a keyframe every 250 frames,
trimmed to a whole number of 250-frame groups so the loop point lands on a keyframe. This matches the files the
pipelines are tuned for. The CPU pipeline's software H.264 encoder is capped at about 4 Mbps by default, so a
higher source bitrate is mostly wasted there.

## Options

| Option | Default | Purpose |
| --- | --- | --- |
| `-o, --output <file.avi>` | `<input name>.avi` | Output file |
| `-n, --frames <N>` | whole 250-frame groups | Write exactly N frames (use the same N for every camera) |
| `-b, --bitrate <rate>` | `4M` | Target bitrate, for example `4M` or `4000k` |
| `-r, --fps <n>` | `30` | Output frame rate |
| `-s, --size <WxH>` | source size | Scale and letterbox to a size, for example `1920x1080` |
| `-g, --gop <n>` | `250` | Keyframe interval in frames |
| `-p, --preset <name>` | `medium` | x264 speed/quality preset (`ultrafast` ... `veryslow`) |
| `--no-trim` | off | Keep every frame instead of trimming to whole groups |
| `-f, --force` | off | Overwrite an existing output |

Run `./scripts/convert_video.sh --help` for the full text.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Output exists` | Add `-f` or choose another `-o` |
| `Could not read a video stream` | The input is not a video file, or its first stream is not video |
| `--frames N is more than the input provides` | Use a smaller N; the clip is shorter than N / 30 seconds |
| `Neither ffmpeg nor docker is installed` | Install Docker or `sudo apt-get install -y ffmpeg` |
| The picture looks soft | Check the source bitrate. A very low-bitrate source cannot be improved by conversion |
