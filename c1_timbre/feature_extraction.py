"""Extract simple audio features and plot filter cutoff vs spectral centroid.

The script intentionally reads every row in the supplied manifest instead of
assuming a fixed dataset size. It only requires NumPy and Pillow, so the
checkpoint analysis can run without a heavyweight audio-analysis stack.
"""

from __future__ import annotations

import argparse
import csv
import math
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "data" / "manifests" / "pilot_v1.csv"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "outputs"
FEATURE_COLUMNS = [
    "sample_id",
    "audio_path",
    "filter_cutoff_normalized",
    "spectral_centroid_hz",
    "spectral_rolloff_85_hz",
    "rms",
    "zero_crossing_rate",
] + [f"mfcc_{index:02d}" for index in range(1, 14)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extract development audio features and create the C1 cutoff/centroid result."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--frame-length", type=int, default=2048)
    parser.add_argument("--hop-length", type=int, default=512)
    return parser.parse_args()


def read_pcm_wav(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        channels = wav_file.getnchannels()
        sample_width = wav_file.getsampwidth()
        frame_count = wav_file.getnframes()
        payload = wav_file.readframes(frame_count)

    dtype_by_width = {1: np.uint8, 2: np.int16, 4: np.int32}
    if sample_width not in dtype_by_width:
        raise ValueError(f"Unsupported PCM sample width ({sample_width}) in {path}")
    samples = np.frombuffer(payload, dtype=dtype_by_width[sample_width]).astype(np.float64)
    if sample_width == 1:
        samples = (samples - 128.0) / 128.0
    else:
        samples /= float(2 ** (8 * sample_width - 1))
    if channels > 1:
        samples = samples.reshape(-1, channels).mean(axis=1)
    return samples, sample_rate


def frame_audio(audio: np.ndarray, frame_length: int, hop_length: int) -> np.ndarray:
    if len(audio) < frame_length:
        audio = np.pad(audio, (0, frame_length - len(audio)))
    remainder = (len(audio) - frame_length) % hop_length
    if remainder:
        audio = np.pad(audio, (0, hop_length - remainder))
    frame_count = 1 + (len(audio) - frame_length) // hop_length
    shape = (frame_count, frame_length)
    strides = (audio.strides[0] * hop_length, audio.strides[0])
    return np.lib.stride_tricks.as_strided(audio, shape=shape, strides=strides).copy()


def hz_to_mel(frequency_hz: np.ndarray | float) -> np.ndarray | float:
    return 2595.0 * np.log10(1.0 + np.asarray(frequency_hz) / 700.0)


def mel_to_hz(mel: np.ndarray | float) -> np.ndarray | float:
    return 700.0 * (10.0 ** (np.asarray(mel) / 2595.0) - 1.0)


def mel_filterbank(sample_rate: int, fft_length: int, filters: int = 40) -> np.ndarray:
    frequencies = np.linspace(0.0, sample_rate / 2.0, fft_length // 2 + 1)
    mel_points = np.linspace(hz_to_mel(0.0), hz_to_mel(sample_rate / 2.0), filters + 2)
    hz_points = mel_to_hz(mel_points)
    bank = np.zeros((filters, len(frequencies)), dtype=np.float64)
    for index in range(filters):
        left, center, right = hz_points[index : index + 3]
        rising = (frequencies - left) / max(center - left, np.finfo(float).eps)
        falling = (right - frequencies) / max(right - center, np.finfo(float).eps)
        bank[index] = np.maximum(0.0, np.minimum(rising, falling))
    return bank


def extract_features(
    audio: np.ndarray,
    sample_rate: int,
    frame_length: int,
    hop_length: int,
) -> dict[str, float]:
    frames = frame_audio(audio, frame_length, hop_length)
    windowed = frames * np.hanning(frame_length)
    spectrum = np.abs(np.fft.rfft(windowed, n=frame_length, axis=1))
    power = spectrum**2
    frequencies = np.fft.rfftfreq(frame_length, d=1.0 / sample_rate)

    magnitude_sum = spectrum.sum(axis=1)
    valid_magnitude = magnitude_sum > np.finfo(float).eps
    centroids = np.zeros(len(frames), dtype=np.float64)
    centroids[valid_magnitude] = spectrum[valid_magnitude] @ frequencies / magnitude_sum[valid_magnitude]

    cumulative_power = np.cumsum(power, axis=1)
    thresholds = cumulative_power[:, -1] * 0.85
    rolloff_bins = np.argmax(cumulative_power >= thresholds[:, None], axis=1)
    rolloff_hz = frequencies[rolloff_bins]

    filterbank = mel_filterbank(sample_rate, frame_length)
    mel_energy = np.maximum(power @ filterbank.T, np.finfo(float).eps)
    log_mel = np.log(mel_energy)
    filter_indexes = np.arange(filterbank.shape[0])
    dct_basis = np.cos(
        np.pi
        / filterbank.shape[0]
        * (filter_indexes[None, :] + 0.5)
        * np.arange(13)[:, None]
    )
    mfcc = (log_mel @ dct_basis.T).mean(axis=0)

    signs = np.signbit(audio)
    zero_crossing_rate = float(np.count_nonzero(signs[1:] != signs[:-1]) / max(len(audio) - 1, 1))
    result = {
        "spectral_centroid_hz": float(centroids.mean()),
        "spectral_rolloff_85_hz": float(rolloff_hz.mean()),
        "rms": float(np.sqrt(np.mean(audio**2))),
        "zero_crossing_rate": zero_crossing_rate,
    }
    result.update({f"mfcc_{index + 1:02d}": float(value) for index, value in enumerate(mfcc)})
    return result


def load_font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
        "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_plot(rows: list[dict[str, float | str]], output_path: Path) -> dict[str, float | int | str]:
    cutoff = np.asarray([float(row["filter_cutoff_normalized"]) for row in rows])
    centroid = np.asarray([float(row["spectral_centroid_hz"]) for row in rows])
    slope, intercept = np.polyfit(cutoff, centroid, 1)
    pearson_r = float(np.corrcoef(cutoff, centroid)[0, 1])
    r_squared = pearson_r**2

    width, height = 1400, 900
    left, right, top, bottom = 145, 75, 150, 130
    plot_left, plot_right = left, width - right
    plot_top, plot_bottom = top, height - bottom
    image = Image.new("RGB", (width, height), "#f7f4ed")
    draw = ImageDraw.Draw(image)
    title_font = load_font(38, bold=True)
    subtitle_font = load_font(22)
    label_font = load_font(24, bold=True)
    tick_font = load_font(18)
    note_font = load_font(19)

    draw.text((left, 38), "C1: Filter cutoff vs spectral centroid", fill="#17221e", font=title_font)
    draw.text(
        (left, 92),
        f"Validated {len(rows)}-sample development set - machine-extracted audio features",
        fill="#597067",
        font=subtitle_font,
    )
    draw.rectangle((plot_left, plot_top, plot_right, plot_bottom), fill="#ffffff", outline="#aab8b0", width=2)

    x_min, x_max = 0.0, 1.0
    y_min = max(0.0, math.floor(float(centroid.min()) / 500.0) * 500.0)
    y_max = math.ceil(float(centroid.max()) / 500.0) * 500.0
    if y_max <= y_min:
        y_max = y_min + 500.0

    def map_x(value: float) -> float:
        return plot_left + (value - x_min) / (x_max - x_min) * (plot_right - plot_left)

    def map_y(value: float) -> float:
        return plot_bottom - (value - y_min) / (y_max - y_min) * (plot_bottom - plot_top)

    for value in np.linspace(0.0, 1.0, 6):
        x = map_x(float(value))
        draw.line((x, plot_top, x, plot_bottom), fill="#e0e6e2", width=1)
        label = f"{value:.1f}"
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text((x - (box[2] - box[0]) / 2, plot_bottom + 15), label, fill="#52615a", font=tick_font)
    for value in np.linspace(y_min, y_max, 6):
        y = map_y(float(value))
        draw.line((plot_left, y, plot_right, y), fill="#e0e6e2", width=1)
        label = f"{value:,.0f}"
        box = draw.textbbox((0, 0), label, font=tick_font)
        draw.text((plot_left - (box[2] - box[0]) - 18, y - 10), label, fill="#52615a", font=tick_font)

    for x_value, y_value in zip(cutoff, centroid, strict=True):
        x, y = map_x(float(x_value)), map_y(float(y_value))
        draw.ellipse((x - 5, y - 5, x + 5, y + 5), fill="#f06445", outline="#b43e2a")

    line_x = np.asarray([0.0, 1.0])
    line_y = slope * line_x + intercept
    draw.line(
        (map_x(float(line_x[0])), map_y(float(line_y[0])), map_x(float(line_x[1])), map_y(float(line_y[1]))),
        fill="#1b6a55",
        width=5,
    )

    x_label = "Filter cutoff (normalized)"
    x_box = draw.textbbox((0, 0), x_label, font=label_font)
    draw.text(((width - (x_box[2] - x_box[0])) / 2, height - 67), x_label, fill="#17221e", font=label_font)
    y_label = "Spectral centroid (Hz)"
    y_label_image = Image.new("RGBA", (350, 50), (0, 0, 0, 0))
    ImageDraw.Draw(y_label_image).text((0, 0), y_label, fill="#17221e", font=label_font)
    y_label_image = y_label_image.rotate(90, expand=True)
    image.paste(y_label_image, (25, int((height - y_label_image.height) / 2)), y_label_image)

    result_text = f"Pearson r = {pearson_r:.3f}   |   R2 = {r_squared:.3f}   |   n = {len(rows)}"
    draw.rounded_rectangle((plot_right - 535, plot_top + 25, plot_right - 25, plot_top + 84), 8, fill="#e6f0eb")
    draw.text((plot_right - 515, plot_top + 42), result_text, fill="#1b6a55", font=note_font)
    image.save(output_path)

    direction = "positive" if slope > 0 else "negative"
    return {
        "sample_count": len(rows),
        "pearson_r": pearson_r,
        "r_squared": r_squared,
        "slope_hz_per_normalized_unit": float(slope),
        "intercept_hz": float(intercept),
        "relationship": direction,
    }


def main() -> None:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    with manifest_path.open(newline="", encoding="utf-8-sig") as manifest_file:
        manifest_rows = list(csv.DictReader(manifest_file))
    if not manifest_rows:
        raise ValueError(f"Manifest contains no rows: {manifest_path}")

    feature_rows: list[dict[str, float | str]] = []
    for index, manifest_row in enumerate(manifest_rows, start=1):
        audio_path = ROOT / Path(manifest_row["audio_path"].replace("\\", "/"))
        if not audio_path.is_file():
            raise FileNotFoundError(f"Missing audio for {manifest_row['sample_id']}: {audio_path}")
        audio, sample_rate = read_pcm_wav(audio_path)
        features = extract_features(audio, sample_rate, args.frame_length, args.hop_length)
        feature_rows.append(
            {
                "sample_id": manifest_row["sample_id"],
                "audio_path": manifest_row["audio_path"],
                "filter_cutoff_normalized": float(manifest_row["filter_cutoff_normalized"]),
                **features,
            }
        )
        print(f"[{index:>3}/{len(manifest_rows)}] {manifest_row['sample_id']}")

    feature_path = output_dir / "c1_audio_features.csv"
    with feature_path.open("w", newline="", encoding="utf-8") as feature_file:
        writer = csv.DictWriter(feature_file, fieldnames=FEATURE_COLUMNS)
        writer.writeheader()
        writer.writerows(feature_rows)

    plot_path = output_dir / "cutoff_vs_centroid.png"
    summary = draw_plot(feature_rows, plot_path)
    summary_path = output_dir / "cutoff_vs_centroid_summary.csv"
    with summary_path.open("w", newline="", encoding="utf-8") as summary_file:
        writer = csv.DictWriter(summary_file, fieldnames=list(summary))
        writer.writeheader()
        writer.writerow(summary)

    print(f"\nWrote {feature_path}")
    print(f"Wrote {plot_path}")
    print(f"Wrote {summary_path}")
    print(
        "Result: "
        f"r={summary['pearson_r']:.3f}, R^2={summary['r_squared']:.3f}, "
        f"slope={summary['slope_hz_per_normalized_unit']:.1f} Hz/unit"
    )


if __name__ == "__main__":
    main()
