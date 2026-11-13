#!/usr/bin/env python3
"""Build a self-contained Apple Silicon .app and drag-to-Applications DMG."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import plistlib
import shutil
import subprocess
import sys
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]


def run(args, **kwargs):
    return subprocess.run([str(arg) for arg in args], check=True, cwd=ROOT, **kwargs)


def build():
    parser = argparse.ArgumentParser()
    parser.add_argument("--version", default="0.1.0")
    parser.add_argument("--identity", default=os.environ.get("TRADEMASTER_SIGN_IDENTITY", "-"))
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--skip-dmg", action="store_true")
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        raise SystemExit("This build currently targets Apple Silicon Macs; run it on macOS arm64.")
    output = ROOT / ".release"
    output.mkdir(exist_ok=True)
    app = output / "TradeMaster.app"
    if app.exists():
        shutil.rmtree(app)
    contents = app / "Contents"
    resources = contents / "Resources"
    (contents / "MacOS").mkdir(parents=True)
    resources.mkdir()
    print("Building the standalone dashboard", flush=True)
    if not args.skip_web:
        env = os.environ.copy()
        env.update(NEXT_DIST_DIR=".next-desktop", TRADEMASTER_DESKTOP_BUILD="1",
                   NEXT_PUBLIC_API_BASE="http://127.0.0.1:18897", NEXT_TELEMETRY_DISABLED="1")
        generated = [ROOT / "apps/web/next-env.d.ts", ROOT / "apps/web/tsconfig.json"]
        original = {path: path.read_bytes() for path in generated}
        try:
            run(["npm", "run", "web:build"], env=env)
        finally:
            for path, value in original.items():
                path.write_bytes(value)
    web_build = ROOT / "apps/web/.next-desktop"
    shutil.copytree(web_build / "standalone", resources / "web", symlinks=True)
    web_root = resources / "web/apps/web"
    shutil.copytree(web_build / "static", web_root / ".next-desktop/static", dirs_exist_ok=True)
    if (ROOT / "apps/web/public").exists():
        shutil.copytree(ROOT / "apps/web/public", web_root / "public", dirs_exist_ok=True)
    for path in (resources / "web").rglob(".env*"):
        if path.is_file():
            path.unlink()
    if not (web_root / "server.js").exists():
        raise SystemExit("Expected standalone monorepo server was not generated.")
    print("Bundling Node and a clean locked Python runtime", flush=True)
    (resources / "node").mkdir()
    node = Path(shutil.which("node")).resolve()
    shutil.copy2(node, resources / "node/node")
    node_version = subprocess.check_output([node, "--version"], text=True).strip()
    local_license = node.parent.parent / "LICENSE"
    if local_license.exists():
        shutil.copy2(local_license, resources / "node/LICENSE")
    else:
        with urlopen(f"https://raw.githubusercontent.com/nodejs/node/{node_version}/LICENSE", timeout=30) as response:
            (resources / "node/LICENSE").write_bytes(response.read())
    # Next's dependency tracing may omit package licenses; retain installed notices.
    notices = resources / "THIRD_PARTY_NOTICES"
    for package in (resources / "web").rglob("package.json"):
        if "node_modules" not in package.parts:
            continue
        meta = json.loads(package.read_text())
        name = meta.get("name", "")
        if not name or ".." in name or name.startswith("/"):
            continue
        source = ROOT / "node_modules" / name
        if not source.is_dir():
            source = package.parent
        for notice in source.iterdir():
            if notice.is_file() and notice.name.lower().startswith(("license", "copying", "notice")):
                dest = notices / name / notice.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(notice, dest)
    base = Path(subprocess.check_output(["uv", "python", "find", "3.12", "--managed-python"], text=True).strip()).resolve().parent.parent
    runtime_key = hashlib.sha256((ROOT / "uv.lock").read_bytes() + str(base).encode()).hexdigest()[:16]
    cache = output / ("python-" + runtime_key)
    if not (cache / ".ready").exists():
        if cache.exists():
            shutil.rmtree(cache)
        shutil.copytree(base, cache, symlinks=True)
        target = cache / "lib/python3.12/site-packages"
        shutil.rmtree(target, ignore_errors=True)
        requirements = output / "desktop-requirements.txt"
        with open(os.devnull, "w") as sink:
            run(["uv", "export", "--frozen", "--no-dev", "--no-emit-project", "--format", "requirements-txt", "--output-file", requirements], stdout=sink)
        run(["uv", "pip", "install", "--python", cache / "bin/python3.12", "--target", target,
             "--require-hashes", "--no-deps", "-r", requirements])
        (cache / ".ready").write_text(runtime_key)
    shutil.copytree(cache, resources / "python", symlinks=True)
    (resources / "python/.ready").unlink()
    # Only first-party tracked source and public documentation; no working databases,
    # credentials, caches, developer environments or experiment artifacts.
    paths = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT).decode().split("\0")
    allowed = ("tradingagents/", "cli/", "scripts/research/", "docs/")
    for name in paths:
        if name and (name.startswith(allowed) or name in {"pyproject.toml", "uv.lock", "LICENSE", "NOTICE", "README.md"}):
            destination = resources / "backend" / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, destination)
    shutil.copytree(ROOT / "desktop", resources / "desktop", ignore=shutil.ignore_patterns("__pycache__"))
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    (resources / "build.json").write_text(json.dumps({"version": args.version, "commit": revision, "architecture": "arm64", "node": subprocess.check_output([node,"--version"],text=True).strip()}, indent=2))
    # All bundled code must remain immutable at runtime (including Python bytecode).
    for path in resources.rglob("__pycache__"):
        if path.is_dir():
            shutil.rmtree(path)
    info = {"CFBundleName": "TradeMaster", "CFBundleDisplayName": "TradeMaster",
            "CFBundleIdentifier": "com.michaeldancurtis.trademaster", "CFBundleExecutable": "TradeMaster",
            "CFBundlePackageType": "APPL", "CFBundleIconFile": "TradeMaster", "CFBundleShortVersionString": args.version,
            "CFBundleVersion": args.version, "LSMinimumSystemVersion": "13.0", "NSHighResolutionCapable": True,
            "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
            "NSHumanReadableCopyright": "Copyright 2026 TradeMaster contributors. Apache-2.0."}
    (contents / "Info.plist").write_bytes(plistlib.dumps(info))
    iconset = output / "TradeMaster.iconset"
    run(["xcrun", "swift", ROOT / "desktop/macos/Icon.swift", iconset])
    run(["iconutil", "-c", "icns", iconset, "-o", resources / "TradeMaster.icns"])
    run(["xcrun", "swiftc", "-O", "-target", "arm64-apple-macos13.0", "-framework", "AppKit", "-framework", "WebKit", ROOT / "desktop/macos/TradeMaster.swift", "-o", contents / "MacOS/TradeMaster"])
    # Mach-O files can be nested inside Python wheels; sign every one inside-out.
    magics = {b'\xcf\xfa\xed\xfe', b'\xce\xfa\xed\xfe', b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'}
    binaries = []
    for path in resources.rglob("*"):
        if path.is_file() and not path.is_symlink():
            with path.open("rb") as handle:
                if handle.read(4) in magics:
                    binaries.append(path)
    sign = ["/usr/bin/codesign", "--force", "--sign", args.identity, "--options", "runtime"]
    if args.identity != "-":
        sign.append("--timestamp")
    print(f"Signing {len(binaries)} bundled binaries", flush=True)
    for index, path in enumerate(sorted(binaries, key=lambda p: len(p.parts), reverse=True)):
        command = sign.copy()
        if path.name in {"node", "python3.12", "python", "python3"}:
            command += ["--entitlements", ROOT / "desktop/macos/runtime-entitlements.plist"]
        run(command + [path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if index % 50 == 0:
            print(f"Signed {index + 1}/{len(binaries)}", flush=True)
    run(sign + [app])
    run(["codesign", "--verify", "--deep", "--strict", "--verbose=2", app])
    if not args.skip_dmg:
        image_root = output / "image"
        if image_root.exists():
            shutil.rmtree(image_root)
        image_root.mkdir()
        # APFS clone preserves the signature and avoids another full data copy.
        run(["ditto", app, image_root / "TradeMaster.app"])
        (image_root / "Applications").symlink_to("/Applications")
        (image_root / "INSTALL.txt").write_text("Drag TradeMaster.app to Applications, then open it.\nRequires macOS 13 or newer on Apple Silicon.\nNo Python, Node, Terminal or source checkout is required.\nConfigure your own providers in Settings.\nData stays in ~/Library/Application Support/TradeMaster.\n")
        dmg = output / f"TradeMaster-{args.version}-macOS-arm64.dmg"
        if dmg.exists():
            dmg.unlink()
        run(["hdiutil", "create", "-volname", "TradeMaster", "-srcfolder", image_root, "-format", "UDZO", dmg])
        if args.identity != "-":
            run(sign + [dmg])
        print(dmg, flush=True)
    print(app, flush=True)


if __name__ == "__main__":
    build()
