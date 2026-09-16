"""The repo root of the Radhouse mark is ``brand/``. Every other copy must be
byte-identical, and no copy may carry a file absent from that source.
"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BRAND_SOURCE = REPO_ROOT / "brand"
COPY_DIRS = [REPO_ROOT / "web" / "assets", REPO_ROOT / "site" / "public"]


def _svg_names(directory: Path) -> set[str]:
    return {path.name for path in directory.glob("*.svg")}


def test_brand_source_exists() -> None:
    assert BRAND_SOURCE.is_dir()
    assert _svg_names(BRAND_SOURCE), "brand/ must contain at least one SVG mark"


def test_copies_match_brand_source_bytes() -> None:
    source_files = sorted(BRAND_SOURCE.glob("*.svg"))
    for copy_dir in COPY_DIRS:
        for source_file in source_files:
            copy_file = copy_dir / source_file.name
            assert copy_file.is_file(), f"{copy_file} is missing; copy it from {source_file}"
            assert copy_file.read_bytes() == source_file.read_bytes(), (
                f"{copy_file} has drifted from {source_file}; "
                "edit brand/ first, then recopy to every listed directory"
            )


def test_copies_have_no_unknown_svgs() -> None:
    source_names = _svg_names(BRAND_SOURCE)
    for copy_dir in COPY_DIRS:
        extra = _svg_names(copy_dir) - source_names
        assert not extra, f"{copy_dir} has SVGs with no source in brand/: {sorted(extra)}"
