from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any

import cv2
import yaml

from dwarves_autoplayer.bot import load_config
from dwarves_autoplayer.playbook import DwarvesPlaybook


ROOT = Path.cwd()
VIDEO_DIR = ROOT / "learning_data" / "videos"
DEFAULT_VIDEO = VIDEO_DIR / "tutorial1.mp4"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video", default=str(DEFAULT_VIDEO), help="Tutorial/playthrough video path.")
    parser.add_argument("--all", action="store_true", help="Process every video in learning_data/videos.")
    parser.add_argument("--interval-seconds", type=float, default=5.0, help="Sampling interval.")
    parser.add_argument("--max-samples", type=int, default=0, help="Optional cap for quick tests.")
    parser.add_argument("--examples-per-state", type=int, default=5, help="Representative frames to save per state.")
    return parser.parse_args()


def output_dir(video_path: Path) -> Path:
    return ROOT / "learning_data" / "video_training" / video_path.stem


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["sample", "time_seconds", "state", "action", "x", "y"])
        writer.writeheader()
        writer.writerows(rows)


def video_paths(args: argparse.Namespace) -> list[Path]:
    if not args.all:
        return [Path(args.video)]

    extensions = {".mp4", ".mkv", ".mov", ".webm", ".avi"}
    paths = [path for path in VIDEO_DIR.glob("*") if path.is_file() and path.suffix.lower() in extensions]
    if not paths:
        raise SystemExit(f"No videos found in {VIDEO_DIR}")
    return sorted(paths, key=lambda item: item.name.lower())


def process_video(video_path: Path, args: argparse.Namespace) -> dict[str, Any]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise SystemExit(f"Could not open video: {video_path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    duration = frame_count / fps if frame_count else 0.0
    step_frames = max(1, int(fps * args.interval_seconds))

    playbook = DwarvesPlaybook(load_config())
    out_dir = output_dir(video_path)
    frames_dir = out_dir / "representative_frames"
    if frames_dir.exists():
        for frame_path in frames_dir.glob("*.png"):
            frame_path.unlink()
    frames_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    examples_for_state: Counter[str] = Counter()
    last_state = "none"

    sample = 0
    frame_index = 0
    while frame_index < frame_count:
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = cap.read()
        if not ok:
            break

        state = playbook.classify(frame).value
        action = playbook.choose_action(frame)
        height, width = frame.shape[:2]
        x = int(width * action.x_ratio) if action else ""
        y = int(height * action.y_ratio) if action else ""
        action_name = action.name if action else ""

        time_seconds = frame_index / fps
        rows.append(
            {
                "sample": sample,
                "time_seconds": round(time_seconds, 2),
                "state": state,
                "action": action_name,
                "x": x,
                "y": y,
            }
        )
        state_counts[state] += 1
        transition_counts[f"{last_state}->{state}"] += 1

        if examples_for_state[state] < args.examples_per_state:
            examples_for_state[state] += 1
            cv2.imwrite(str(frames_dir / f"{state}_{examples_for_state[state]:02d}_{int(time_seconds):05d}s.png"), frame)

        last_state = state
        sample += 1
        if args.max_samples and sample >= args.max_samples:
            break
        frame_index += step_frames

    cap.release()

    write_csv(out_dir / "timeline.csv", rows)
    summary = {
        "video": str(video_path),
        "fps": fps,
        "frame_count": frame_count,
        "duration_seconds": duration,
        "interval_seconds": args.interval_seconds,
        "samples": len(rows),
        "state_counts": dict(state_counts),
        "transitions": dict(transition_counts),
    }

    with (out_dir / "summary.json").open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)

    print(f"Video: {video_path}")
    print(f"Duration: {duration:.1f}s, samples: {len(rows)}")
    print(f"Wrote: {out_dir / 'timeline.csv'}")
    print(f"Wrote: {out_dir / 'summary.json'}")
    print("State counts:")
    for state, count in state_counts.most_common():
        print(f"  {state}: {count}")
    print()

    return summary


def aggregate_summaries(summaries: list[dict[str, Any]], interval_seconds: float) -> dict[str, Any]:
    state_counts: Counter[str] = Counter()
    transition_counts: Counter[str] = Counter()
    total_duration = 0.0
    total_samples = 0

    for summary in summaries:
        state_counts.update(summary.get("state_counts", {}))
        transition_counts.update(summary.get("transitions", {}))
        total_duration += float(summary.get("duration_seconds", 0.0))
        total_samples += int(summary.get("samples", 0))

    return {
        "videos": [
            {
                "video": summary["video"],
                "duration_seconds": summary["duration_seconds"],
                "samples": summary["samples"],
                "state_counts": summary["state_counts"],
            }
            for summary in summaries
        ],
        "interval_seconds": interval_seconds,
        "total_duration_seconds": total_duration,
        "total_samples": total_samples,
        "aggregate_state_counts": dict(state_counts),
        "aggregate_transitions": dict(transition_counts),
    }


def main() -> None:
    args = parse_args()
    summaries = [process_video(path, args) for path in video_paths(args)]
    aggregate = aggregate_summaries(summaries, args.interval_seconds)

    baseline_path = ROOT / "knowledge" / "video_baseline.yaml"
    baseline_path.parent.mkdir(parents=True, exist_ok=True)
    with baseline_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(aggregate, handle, sort_keys=False)

    print(f"Wrote aggregate baseline: {baseline_path}")
    print("Aggregate state counts:")
    for state, count in Counter(aggregate["aggregate_state_counts"]).most_common():
        print(f"  {state}: {count}")


if __name__ == "__main__":
    main()
