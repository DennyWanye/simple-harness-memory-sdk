#!/usr/bin/env python3
"""Write immutable CI candidate metadata beside one wheel and one sdist."""

from __future__ import annotations

import argparse
import hashlib
import re
import zipfile
from email.parser import BytesParser
from pathlib import Path

PACKAGE = "simple-harness-memory-sdk"
VERSION = "0.6.0"
HARNESS_REQUIRES = "simple-harness-sdk<0.8,>=0.7"


class CandidateMetadataError(RuntimeError):
    """Fail-closed candidate metadata validation error."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _wheel_identity(path: Path) -> tuple[str, str, str, tuple[str, ...]]:
    try:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist() if name.endswith(".dist-info/METADATA")]
            if len(names) != 1:
                raise CandidateMetadataError("candidate-wheel-metadata-invalid")
            metadata = BytesParser().parsebytes(archive.read(names[0]))
    except (OSError, zipfile.BadZipFile) as exc:
        raise CandidateMetadataError("candidate-wheel-invalid") from exc
    return (
        str(metadata.get("Name", "")),
        str(metadata.get("Version", "")),
        str(metadata.get("Requires-Python", "")),
        tuple(str(value) for value in metadata.get_all("Requires-Dist", [])),
    )


def write_metadata(dist: Path, source_commit: str, build_utc: str) -> None:
    if not dist.is_dir() or dist.is_symlink():
        raise CandidateMetadataError("candidate-dist-invalid")
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise CandidateMetadataError("candidate-source-commit-invalid")
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", build_utc) is None:
        raise CandidateMetadataError("candidate-build-utc-invalid")
    wheel_files = sorted(dist.glob("*.whl"))
    sdist_files = sorted((*dist.glob("*.tar.gz"), *dist.glob("*.zip")))
    if len(wheel_files) != 1 or len(sdist_files) != 1:
        raise CandidateMetadataError("candidate-artifacts-ambiguous")
    if any(path.is_symlink() or not path.is_file() for path in (*wheel_files, *sdist_files)):
        raise CandidateMetadataError("candidate-artifact-invalid")
    wheel = wheel_files[0]
    name, version, requires_python, requirements = _wheel_identity(wheel)
    if (name, version) != (PACKAGE, VERSION) or requires_python != "<3.14,>=3.11":
        raise CandidateMetadataError("candidate-wheel-identity-invalid")
    if not any(
        value.startswith(HARNESS_REQUIRES) and "extra == 'harness'" in value
        for value in requirements
    ):
        raise CandidateMetadataError("candidate-harness-extra-invalid")
    if not any(
        value.startswith(HARNESS_REQUIRES) and "extra ==" not in value
        for value in requirements
    ):
        raise CandidateMetadataError("candidate-harness-base-dependency-invalid")
    outputs = (dist / "SHA256SUMS", dist / "BUILD_INFO.txt")
    if any(path.exists() for path in outputs):
        raise CandidateMetadataError("candidate-metadata-already-exists")
    artifacts = tuple(sorted((*wheel_files, *sdist_files), key=lambda path: path.name))
    digests = {path.name: _sha256(path) for path in artifacts}
    outputs[0].write_text(
        "".join(f"{digests[path.name]}  {path.name}\n" for path in artifacts),
        encoding="utf-8",
    )
    outputs[1].write_text(
        "\n".join(
            (
                f"package={PACKAGE}",
                f"version={VERSION}",
                f"source_commit={source_commit}",
                f"requires_python={requires_python}",
                f"harness_requires={HARNESS_REQUIRES}",
                f"build_utc={build_utc}",
                f"wheel_sha256={digests[wheel.name]}",
                f"sdist_sha256={digests[sdist_files[0].name]}",
                "",
            )
        ),
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--build-utc", required=True)
    args = parser.parse_args()
    try:
        write_metadata(args.dist, args.source_commit, args.build_utc)
    except CandidateMetadataError as exc:
        parser.exit(1, f"{exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
