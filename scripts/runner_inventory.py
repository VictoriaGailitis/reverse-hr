"""Inventory a provisioned/reviewed rootfs; never install or execute it."""

import argparse
from pathlib import Path

from reverse_hr.services.code_runner.sandbox import digest, inventory

parser = argparse.ArgumentParser()
parser.add_argument("--rootfs", required=True, type=Path)
parser.add_argument("--output", required=True, type=Path)
parser.add_argument("--architecture", choices=["x86_64", "aarch64"], default="x86_64")
args = parser.parse_args()
if not args.rootfs.is_dir() or args.rootfs.resolve() == Path("/"):
    parser.error("Select a dedicated rootfs directory")
if args.output.resolve().is_relative_to(args.rootfs.resolve()):
    parser.error("Keep the approval manifest outside the rootfs")
manifest = inventory(args.rootfs, architecture=args.architecture)
with args.output.open("x", encoding="utf-8") as output:
    output.write(manifest.model_dump_json(indent=2) + "\n")
args.output.chmod(0o600)
print("rootfs_manifest_sha256=" + digest(args.output))
