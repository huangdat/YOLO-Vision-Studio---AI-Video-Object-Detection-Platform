"""Fetch selected MOT17 training sequences from the official archive without the full 5.9 GB download.

MOT17 (https://motchallenge.net/data/MOT17/) is licensed CC BY-NC-SA 3.0: non-commercial use with
attribution; derived works under the same license. Data is written only to a local, git-ignored
directory and must never be committed or redistributed from this repository.

The official ``MOT17.zip`` is read through HTTP range requests: only the zip index and the members
of the requested sequences are transferred. Every extracted file is verified by the zip's CRC-32.

    python -m benchmarks.fetch_mot17 --list
    python -m benchmarks.fetch_mot17 --sequences MOT17-05 MOT17-09 --dest temp/datasets/MOT17 --max-mb 600

Each MOT17 sequence appears three times in the archive (``-DPM``, ``-FRCNN``, ``-SDP``) with identical
images and ground truth (only the public detections differ, which this project does not use);
``--variant`` picks one (default FRCNN).
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import io
from pathlib import Path
import sys
import urllib.request
import zipfile

ARCHIVE_URL = "https://motchallenge.net/data/MOT17.zip"
BLOCK = 8 * 1024 * 1024
USER_AGENT = "yolo-vision-studio-evaluation/1.0"


class HttpRangeFile(io.RawIOBase):
    """Read-only, seekable view of a remote file using HTTP Range requests and an 8 MB block cache."""

    def __init__(self, url: str) -> None:
        self.url = url
        request = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=60) as response:
            if response.headers.get("Accept-Ranges") != "bytes":
                raise RuntimeError("The server does not support range requests")
            self.size = int(response.headers["Content-Length"])
        self.position = 0
        self.transferred = 0
        self._block_start = -1
        self._block = b""

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.position

    def seek(self, offset: int, whence: int = 0) -> int:
        base = {0: 0, 1: self.position, 2: self.size}[whence]
        self.position = max(0, base + offset)
        return self.position

    def _fetch(self, start: int) -> None:
        end = min(self.size, start + BLOCK) - 1
        request = urllib.request.Request(self.url, headers={"Range": f"bytes={start}-{end}", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 206:
                raise RuntimeError(f"Expected a partial response, got HTTP {response.status}")
            self._block = response.read()
        self._block_start = start
        self.transferred += len(self._block)

    def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            size = self.size - self.position
        chunks = []
        while size > 0 and self.position < self.size:
            if not (self._block_start <= self.position < self._block_start + len(self._block)):
                self._fetch(self.position)
            offset = self.position - self._block_start
            chunk = self._block[offset:offset + size]
            chunks.append(chunk)
            self.position += len(chunk)
            size -= len(chunk)
        return b"".join(chunks)

    def readinto(self, buffer) -> int:  # type: ignore[no-untyped-def]
        data = self.read(len(buffer))
        buffer[:len(data)] = data
        return len(data)


def sequence_members(archive: zipfile.ZipFile, variant: str) -> dict[str, list[zipfile.ZipInfo]]:
    sequences: dict[str, list[zipfile.ZipInfo]] = defaultdict(list)
    for info in archive.infolist():
        parts = info.filename.split("/")
        # MOT17/train/MOT17-09-FRCNN/{seqinfo.ini, gt/gt.txt, img1/000001.jpg, det/det.txt}
        if len(parts) >= 4 and parts[1] == "train" and parts[2].endswith(f"-{variant}") and not info.is_dir():
            if parts[3] in {"seqinfo.ini", "gt", "img1"}:
                sequences[parts[2].rsplit("-", 1)[0]].append(info)
    return dict(sequences)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--list", action="store_true", help="List training sequences and their sizes")
    parser.add_argument("--sequences", nargs="*", default=[], help="e.g. MOT17-05 MOT17-09")
    parser.add_argument("--variant", default="FRCNN", choices=("FRCNN", "DPM", "SDP"))
    parser.add_argument("--dest", type=Path, default=Path("temp/datasets/MOT17"))
    parser.add_argument("--max-mb", type=float, default=600, help="Refuse to transfer more than this")
    parser.add_argument("--every", type=int, default=1,
                        help="Keep every Nth frame only (calibration sources); implies --images-only")
    parser.add_argument("--images-only", action="store_true", help="Skip ground truth (calibration sources)")
    args = parser.parse_args(argv)

    remote = HttpRangeFile(ARCHIVE_URL)
    archive = zipfile.ZipFile(io.BufferedReader(remote, buffer_size=BLOCK))
    sequences = sequence_members(archive, args.variant)
    if args.list or not args.sequences:
        for name, members in sorted(sequences.items()):
            images = sum(1 for info in members if "/img1/" in info.filename)
            size = sum(info.compress_size for info in members)
            print(f"{name}  {images:5d} frames  {size / 1e6:8.1f} MB")
        print(f"(index read: {remote.transferred / 1e6:.1f} MB of {remote.size / 1e9:.2f} GB)")
        return 0
    unknown = sorted(set(args.sequences) - set(sequences))
    if unknown:
        parser.error(f"Unknown training sequences: {', '.join(unknown)}")
    images_only = args.images_only or args.every > 1

    def wanted(info: zipfile.ZipInfo) -> bool:
        if "/img1/" not in info.filename:
            return not images_only
        return int(Path(info.filename).stem) % args.every == 1 % args.every

    sequences = {name: [info for info in members if wanted(info)] for name, members in sequences.items()}
    planned = sum(info.compress_size for name in args.sequences for info in sequences[name])
    if planned > args.max_mb * 1e6:
        parser.error(f"The selection is {planned / 1e6:.0f} MB, above --max-mb {args.max_mb:.0f}")
    for name in args.sequences:
        target = args.dest / f"{name}-{args.variant}"
        members = sorted(sequences[name], key=lambda info: info.header_offset)  # sequential reads
        for info in members:
            relative = info.filename.split("/", 3)[3]
            path = target / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source:  # raises BadZipFile on a CRC-32 mismatch
                path.write_bytes(source.read())
        print(f"{name}-{args.variant}: {len(members)} files -> {target}", file=sys.stderr)
    print(f"Transferred {remote.transferred / 1e6:.1f} MB (selection {planned / 1e6:.1f} MB compressed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
