"""Zip the Chrome extension as dist/liscia-agent-chrome-extension-<version>.zip.
The manifest inside the zip is stamped with <version> (the repo's manifest is left alone).
Usage: python scripts/build_extension_zip.py [version]   (default: version from chrome-extension/manifest.json)"""
import json, os, re, sys, zipfile

def build(version=None, root=None, out_dir=None):
    root = root or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ext = os.path.join(root, "chrome-extension")
    manifest = json.load(open(os.path.join(ext, "manifest.json"), encoding="utf-8"))
    version = (version or manifest["version"]).lstrip("v")
    if not re.fullmatch(r"\d+(\.\d+){0,3}", version):
        raise SystemExit(f"bad version {version!r} (Chrome needs 1-4 dot-separated numbers)")
    manifest["version"] = version
    out_dir = out_dir or os.path.join(root, "dist"); os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"liscia-agent-chrome-extension-{version}.zip")
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for dp, _, files in os.walk(ext):
            for f in sorted(files):
                full = os.path.join(dp, f); rel = os.path.relpath(full, ext).replace(os.sep, "/")
                if rel == "manifest.json":
                    z.writestr(rel, json.dumps(manifest, indent=2) + "\n")
                elif not f.startswith(".") and "__pycache__" not in rel:
                    z.write(full, rel)
    return out

if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else None))
