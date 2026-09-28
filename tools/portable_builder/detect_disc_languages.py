#!/usr/bin/env python3
"""Read Dante's Inferno disc text-language manifest from EA BIGH/VIV archives.

This is a conservative Python port of upstream LanguageManifest.cs. It reports
only the text-language records whose format is known upstream. The manifest's
audio count is retained as metadata, but audio-language record layout is not
guessed here.
"""

from __future__ import annotations

import argparse
import json
import re
import struct
from pathlib import Path

BIG_MAGIC = 0x42494748  # "BIGH"
SIGNATURE = re.compile(r"^\d+\r?\n[0-9A-Fa-f]{8}-[0-9A-Fa-f]{2}")

LANGUAGE_NAMES = {
    1: "English",
    2: "Japanese",
    3: "German",
    4: "French",
    5: "Spanish",
    6: "Italian",
    7: "Korean",
    8: "Chinese (Traditional)",
    9: "Portuguese",
    10: "Chinese (Simplified)",
    11: "Polish",
    12: "Russian",
}


def parse_manifest(text: str) -> dict | None:
    if not SIGNATURE.search(text):
        return None

    lines = text.split("\n")
    normalized = [line.rstrip("\r") for line in lines]
    try:
        p = normalized.index("default")
    except ValueError:
        return None
    if p + 2 >= len(normalized):
        return None

    try:
        text_count = int(normalized[p + 1])
        audio_count = int(normalized[p + 2])
    except ValueError:
        return None
    if not 1 <= text_count <= 32:
        return None
    if not 0 <= audio_count <= 32:
        return None

    cursor = p + 3
    languages: list[dict] = []
    for _ in range(text_count):
        if cursor + 3 >= len(normalized):
            return None
        try:
            language_id = int(normalized[cursor + 2])
        except ValueError:
            return None
        manifest_name = normalized[cursor + 1].strip()
        code = normalized[cursor].strip()
        tag = normalized[cursor + 3].strip()
        if 1 <= language_id <= 12 and manifest_name:
            languages.append(
                {
                    "id": language_id,
                    "name": LANGUAGE_NAMES.get(language_id, manifest_name),
                    "manifest_name": manifest_name,
                    "code": code,
                    "tag": tag,
                }
            )
        cursor += 4

    if not languages:
        return None

    return {
        "signature_line": normalized[1] if len(normalized) > 1 else "",
        "text_count": text_count,
        "audio_count": audio_count,
        "text_languages": languages,
    }


def try_read_viv(path: Path) -> dict | None:
    try:
        with path.open("rb") as f:
            header = f.read(16)
            if len(header) < 16:
                return None
            magic = struct.unpack(">I", header[0:4])[0]
            if magic != BIG_MAGIC:
                return None
            num_files = struct.unpack(">I", header[8:12])[0]

            entries: list[tuple[int, int]] = []
            for _ in range(num_files):
                raw = f.read(12)
                if len(raw) < 12:
                    return None
                offset = struct.unpack(">I", raw[0:4])[0]
                size = struct.unpack(">I", raw[4:8])[0]
                entries.append((offset, size))

            file_size = path.stat().st_size
            for offset, size in entries:
                if size < 32 or size > 8192:
                    continue
                if offset + size > file_size:
                    continue
                f.seek(offset)
                data = f.read(size)
                text = data.decode("ascii", errors="replace")
                parsed = parse_manifest(text)
                if parsed is not None:
                    parsed["archive"] = path.name
                    parsed["manifest_offset"] = offset
                    parsed["manifest_size"] = size
                    return parsed
    except (OSError, struct.error):
        return None
    return None


def detect_game_dir(game_dir: Path) -> dict:
    result = {
        "schema": 1,
        "found": False,
        "game_dir": str(game_dir),
        "archives_checked": [],
        "manifest": None,
    }
    if not game_dir.is_dir():
        result["error"] = "game directory not found"
        return result

    archives = sorted(
        (
            entry
            for entry in game_dir.iterdir()
            if entry.is_file()
            and entry.name.lower().startswith("bigfile")
            and entry.suffix.lower() == ".viv"
        ),
        key=lambda p: p.name.lower(),
    )
    result["archives_checked"] = [path.name for path in archives]
    for path in archives:
        parsed = try_read_viv(path)
        if parsed is not None:
            result["found"] = True
            result["manifest"] = parsed
            break
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("game_dir")
    parser.add_argument("--json", dest="json_path")
    args = parser.parse_args()

    result = detect_game_dir(Path(args.game_dir))
    if args.json_path:
        path = Path(args.json_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")

    if not result["found"]:
        print("Disc language manifest: not found")
        print("Archives checked:", ", ".join(result["archives_checked"]) or "none")
        return 0

    manifest = result["manifest"]
    assert manifest is not None
    print(
        f"Disc language manifest: {manifest['archive']} "
        f"({manifest['signature_line']})"
    )
    print(
        "Text languages:",
        ", ".join(
            f"{item['name']} (ID {item['id']})"
            for item in manifest["text_languages"]
        ),
    )
    print("Manifest audio language count:", manifest["audio_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
