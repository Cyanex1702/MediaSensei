"""Bounded FFmpeg operations; arguments are constructed without a shell."""

from __future__ import annotations

import math
import re
from dataclasses import asdict

from mediasensei.infrastructure.media import FFmpegToolchain, MediaPipeline


def media_plan(store, path, modality, p):
    pipeline = MediaPipeline(store)
    info = pipeline.inspect(path)
    if not info.valid:
        raise ValueError(info.error)
    if str(info.media_kind) != modality:
        raise ValueError("The selected asset does not match this lab.")
    length = float(info.duration_seconds or 0)
    start = float(p.get("start", 0))
    duration = float(p.get("duration", 0)) or max(0, length - start)
    if length <= 0 or start >= length:
        raise ValueError("Start must be within a media file with known duration.")
    duration = min(duration, length - start)
    if modality == "video":
        mode = p["sampling"]
        interval = float(p["interval"])
        count = int(p["count"])
        if mode == "seconds":
            count = math.ceil(duration / interval)
        elif mode == "frames":
            if not info.fps:
                raise ValueError("Frame sampling requires known source FPS.")
            if interval < 1 or not interval.is_integer():
                raise ValueError("Every N frames requires a positive whole number.")
            count = math.ceil(duration * info.fps / interval)
        if p["action"] in ("frames", "contact_sheet", "scenes") and count > 500:
            raise ValueError(
                f"Estimated {count} frames exceeds the 500 frame limit; increase interval or trim duration."
            )
        estimate = {"frames": count, "estimate": mode in ("scene", "frames"), "max_frames": 500}
    else:
        segments = math.ceil(duration / float(p["segment_seconds"]))
        if p["action"] == "segment" and segments > 500:
            raise ValueError("Segmentation exceeds 500 outputs; increase segment length.")
        estimate = {"segments": segments}
    return {"analysis": asdict(info), "start": start, "duration": duration, **estimate}


def process_media(store, path, modality, p, directory):
    plan = media_plan(store, path, modality, p)
    tools = FFmpegToolchain()
    report = {**plan, "tool_revision": tools.version}
    output = []
    action = p["action"]
    if action == "inspect":
        return report, output
    base = [
        str(tools.ffmpeg),
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "info",
        "-ss",
        str(plan["start"]),
        "-i",
        str(path),
    ]
    tail = ["-map_metadata", "-1", "-threads", "1", "-y"]
    duration = plan["duration"]

    def run(args, name=None, mime=None):
        destination = directory / name if name else None
        command = [*base, "-t", str(duration), *args]
        command += [*tail, str(destination)] if destination else ["-f", "null", "-"]
        completed = tools._run(command, timeout=1800)
        if destination:
            if not destination.is_file() or destination.stat().st_size == 0:
                raise ValueError(
                    "No output was produced; review the selected interval and filters."
                )
            output.append((destination, mime))
        return completed.stderr or ""

    if modality == "video" and action in ("frames", "contact_sheet", "scenes", "thumbnail"):
        count = 1 if action == "thumbnail" else plan["frames"]
        mode = "scene" if action == "scenes" else p["sampling"]
        if action == "thumbnail":
            selection = "select=eq(n\\,0)"
        elif mode == "scene":
            selection = f"select=gt(scene\\,{p['scene_threshold']})"
        elif mode == "frames":
            selection = f"select=not(mod(n\\,{int(p['interval'])}))"
        elif mode == "seconds":
            selection = f"fps=1/{p['interval']}"
        else:
            selection = f"fps={count / duration}"
        width = min(int(p["width"]), 1280)
        pattern = directory / "frame-%05d.jpg"
        command = [
            *base,
            "-t",
            str(duration),
            "-an",
            "-vf",
            f"{selection},scale={width}:-2,showinfo",
            "-fps_mode",
            "vfr",
            "-frames:v",
            str(count),
            *tail,
            str(pattern),
        ]
        completed = tools._run(command, timeout=1800)
        files = sorted(directory.glob("frame-*.jpg"))
        stamps = [
            float(v) + plan["start"]
            for v in re.findall(r"pts_time:([\d.]+)", completed.stderr or "")
        ][: len(files)]
        report.update(
            actual_frames=len(files),
            timestamps=stamps,
            sampling=mode,
            scene_threshold=p["scene_threshold"] if mode == "scene" else None,
        )
        if action == "contact_sheet" and files:
            from PIL import Image, ImageDraw, ImageOps

            cols = min(5, len(files))
            canvas = Image.new("RGB", (cols * 256, math.ceil(len(files) / cols) * 170), "#102019")
            draw = ImageDraw.Draw(canvas)
            for i, f in enumerate(files):
                with Image.open(f) as im:
                    thumb = ImageOps.contain(im, (256, 144))
                    x, y = i % cols * 256, i // cols * 170
                    canvas.paste(thumb, (x, y))
                    draw.text(
                        (x + 6, y + 148),
                        f"{stamps[i]:.2f}s" if i < len(stamps) else str(i + 1),
                        fill="white",
                    )
            destination = directory / "contact-sheet.jpg"
            canvas.save(destination, quality=85)
            output.append((destination, "image/jpeg"))
        else:
            output.extend((f, "image/jpeg") for f in files)
        return report, output
    if modality == "audio" and action in ("waveform", "spectrogram"):
        filt = (
            "showwavespic=s=1200x260:colors=66efc0"
            if action == "waveform"
            else "showspectrumpic=s=1200x512:legend=1"
        )
        run(
            ["-lavfi", f"atrim=duration={duration},{filt}", "-frames:v", "1", "-an"],
            f"{action}.png",
            "image/png",
        )
    elif modality == "audio" and action in ("silence", "features"):
        filt = (
            f"silencedetect=noise={p['silence_db']}dB:d={p['silence_seconds']}"
            if action == "silence"
            else "astats=metadata=0:reset=0"
        )
        detail = run(["-vn", "-af", filt])
        if action == "silence":
            starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", detail)]
            ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", detail)]
            report["silence_intervals"] = [
                {
                    "start": s + plan["start"],
                    "end": (ends[i] if i < len(ends) else duration) + plan["start"],
                }
                for i, s in enumerate(starts)
            ]
        else:
            overall = detail.split("Overall")[-1]
            report["features"] = {
                key.strip(): val.strip()
                for key, val in re.findall(r"\] ([A-Za-z /_]+): ([^\r\n]+)", overall)
            }
        report["analysis_log"] = detail[-12000:]
    else:
        audio = modality == "audio" or action == "extract_audio"
        fmt = p["audio_format"] if action == "extract_audio" else p["format"]
        if audio:
            codec = {
                "wav": ["-c:a", "pcm_s16le"],
                "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
                "flac": ["-c:a", "flac"],
                "ogg": ["-c:a", "libopus"],
            }[fmt]
            args = ["-map", "0:a:0", "-vn", *codec]
            if modality == "audio":
                rate = 48000 if fmt == "ogg" else int(p["sample_rate"])
                if fmt == "mp3" and rate not in (8000, 11025, 12000, 16000, 22050, 24000, 32000, 44100, 48000):
                    raise ValueError("MP3 requires a supported sample rate between 8000 and 48000 Hz.")
                report["output_sample_rate"] = rate
                args += ["-ar", str(rate), "-ac", p["channels"]]
                if action == "normalize":
                    args += ["-af", f"loudnorm=I={p['loudness']}:TP=-1.5:LRA=11"]
                elif action == "remove_silence":
                    args += [
                        "-af",
                        f"silenceremove=start_periods=1:start_duration={p['silence_seconds']}:start_threshold={p['silence_db']}dB:stop_periods=-1:stop_duration={p['silence_seconds']}:stop_threshold={p['silence_db']}dB",
                    ]
            mime = {
                "wav": "audio/wav",
                "mp3": "audio/mpeg",
                "flac": "audio/flac",
                "ogg": "audio/ogg",
            }[fmt]
            if action == "segment":
                pattern = directory / f"segment-%05d.{fmt}"
                tools._run(
                    [
                        *base,
                        "-t",
                        str(duration),
                        *args,
                        "-f",
                        "segment",
                        "-segment_time",
                        str(p["segment_seconds"]),
                        "-reset_timestamps",
                        "1",
                        *tail,
                        str(pattern),
                    ],
                    timeout=1800,
                )
                output.extend((f, mime) for f in sorted(directory.glob(f"segment-*.{fmt}")))
                report["actual_segments"] = len(output)
            else:
                run(args, f"{action}.{fmt}", mime)
        else:
            width, height = int(p["width"]) // 2 * 2, int(p["height"]) // 2 * 2
            args = [
                "-map",
                "0:v:0",
                "-map",
                "0:a?",
                "-vf",
                f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2",
            ]
            if p["fps"]:
                args += ["-r", str(p["fps"])]
            args += (
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "23",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                ]
                if fmt == "mp4"
                else ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-c:a", "libopus"]
            )
            run(args, f"{action}.{fmt}", f"video/{fmt}")
    return report, output
