"""Stable package/resource roots for isolated workers and packaged assets."""

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PACKAGE_ROOT.parent
REPOSITORY_ROOT = SOURCE_ROOT.parent
