"""Freeze a disposable build context from exact public source and native bytes."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def sha(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_native_provenance(lock):
    if lock.get('native_variant') != 'page_only':
        return
    for name, key in (('native-page-only-lock.json', 'native_variant_lock_sha256'),
            ('native-page-only-build.json', 'native_variant_build_receipt_sha256')):
        if sha(HERE/name) != lock[key]:
            raise ValueError('native_provenance_mismatch')
    receipt = json.loads((HERE/'native-page-only-build.json').read_text())
    if (receipt['native_binary_sha256'] != lock['native_binary_sha256']
            or receipt['variant_source_lock_sha256'] != lock['native_variant_lock_sha256']):
        raise ValueError('native_provenance_mismatch')


def prepare(archive, native, chrome_archive, output):
    lock = json.loads((HERE / "source-lock.json").read_text())
    verify_native_provenance(lock)
    if sha(archive) != lock["selkies_archive_sha256"] or sha(native) != lock["native_binary_sha256"]:
        raise ValueError("source_identity_mismatch")
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    upstream = output / "upstream"
    upstream.mkdir()
    with tarfile.open(archive) as tar:
        tar.extractall(upstream, filter="data")
    members = list(upstream.iterdir())
    if len(members) != 1 or not members[0].is_dir():
        raise ValueError("unexpected_source_layout")
    source = members[0]
    target = source / "addons/selkies-web-core/selkies-ws-core.js"
    before = target.read_text()
    anchor = """    isSharedMode: () => isSharedMode,
    canSync: () => !!window.clipboard_enabled && clipboard_seamless,
"""
    if before.count(anchor) != 1:
        raise ValueError("clipboard_patch_anchor_changed")
    patched = before.replace(anchor,
        "    isSharedMode: () => isSharedMode,\n    canSync: () => false, // Radhouse: deliberate paste only; no focus/initial read.\n")
    gesture = "canSync: () => !isSharedMode && !!window.clipboard_enabled && clipboard_seamless,"
    if patched.count(gesture) != 1:
        raise ValueError("clipboard_gesture_anchor_changed")
    patched = patched.replace(gesture,
        "canSync: () => !!window.webrtcInput?.isInputAttached() && !!window.clipboard_enabled && clipboard_seamless,")
    warning = 'console.warn("initializeInput: WebSocket not open, cannot send input message:", message);'
    if patched.count(warning) != 1:
        raise ValueError("input_logging_anchor_changed")
    patched = patched.replace(warning, 'console.warn("Stream input unavailable.");')
    target.write_text(patched)
    gestures = source / "addons/selkies-web-core/lib/clipboard-sync.js"
    text = gestures.read_text()
    changes = (
        ("const awaitsPasteEvent = !isChromium && chord", "const awaitsPasteEvent = chord"),
        ("if (isChromium) ev.preventDefault();", "if (isChromium && !awaitsPasteEvent) ev.preventDefault();"),
        ("""        if (!isChromium) {
            window.addEventListener('keydown', onCopyKeydown, true);
            window.addEventListener('paste', onPaste, true);
        }""", """        window.addEventListener('keydown', onCopyKeydown, true);
        window.addEventListener('paste', onPaste, true);"""),
        ("""        if (!isChromium) {
            window.removeEventListener('keydown', onCopyKeydown, true);
            window.removeEventListener('paste', onPaste, true);
        }""", """        window.removeEventListener('keydown', onCopyKeydown, true);
        window.removeEventListener('paste', onPaste, true);"""),
    )
    for anchor, replacement in changes:
        if text.count(anchor) != 1:
            raise ValueError("deliberate_clipboard_anchor_changed")
        text = text.replace(anchor, replacement)
    gestures.write_text(text)
    core = source / "addons/selkies-web-core"
    subprocess.run(["npm", "ci", "--no-audit", "--no-fund"], cwd=core, check=True)
    # The upstream postbuild fetches a moving gamepad database. Gamepads are
    # outside this candidate, so build only the locked rendering/input core.
    subprocess.run(["npm", "--ignore-scripts", "run", "build"], cwd=core, check=True)
    shutil.copytree(core / "dist", output / "selkies-web")
    shutil.copytree(core, output / "client-source", ignore=shutil.ignore_patterns("node_modules", "dist"))
    shutil.copyfile(source / "LICENSE", output / "client-source/LICENSE")
    shutil.copyfile(HERE / "web/stream-bridge.js", output / "selkies-web/bridge.js")
    index = output / "selkies-web/index.html"
    index.write_text(index.read_text().replace("</head>", '<script src="bridge.js"></script></head>'))
    # Selkies packages its frontend; the qualification instead serves the core
    # directly in Radhouse's iframe, without the upstream desktop dashboard.
    bundle = source / "src/selkies/selkies_web"
    bundle.mkdir()
    (bundle / "__init__.py").write_text('"""Radhouse serves the separately frozen core."""\n')
    shutil.copytree(source / "src", output / "selkies-src")
    for name in ("pyproject.toml", "README.md", "LICENSE"):
        shutil.copyfile(source / name, output / name)
    shutil.copytree(HERE, output / "candidate/runtime/selkies", ignore=shutil.ignore_patterns("__pycache__"))
    (output / "candidate/runtime/hermes").mkdir(parents=True)
    for name in ("browser_control.py", "native_control.py"):
        shutil.copyfile(ROOT / "runtime/hermes" / name, output / "candidate/runtime/hermes" / name)
    browser = output / "browser"
    browser.mkdir()
    shutil.copyfile(native, browser / "agent-browser")
    (browser / "agent-browser").chmod(0o755)
    with tarfile.open(chrome_archive) as tar:
        tar.extractall(browser, filter="data")
    if sha(browser / "chrome-linux64/chrome") != lock["chromium_binary_sha256"]:
        raise ValueError("chromium_identity_mismatch")
    (browser / "empty.json").write_text("{}\n")
    shutil.copyfile(ROOT / "runtime/hermes/native-view-only/AGENT-BROWSER-LICENSE.txt", browser / "AGENT-BROWSER-LICENSE.txt")
    shutil.copyfile(HERE / "Dockerfile", output / "Dockerfile")
    shutil.copyfile(HERE / "requirements.txt", output / "requirements.txt")
    receipt = {**lock, "patched_clipboard_source_sha256": sha(target),
        "patched_clipboard_gestures_sha256": sha(gestures),
        "served_core_sha256": sha(output / "selkies-web/selkies-core.js"),
        "candidate_files": {str(p.relative_to(output / "candidate")):sha(p)
            for p in sorted((output / "candidate").rglob("*")) if p.is_file()},
        "sandbox_qualified": False, "available_modes": ["fixture", "public_web"], "synthetic_only": False}
    (output / "build-inputs.json").write_text(json.dumps(receipt, indent=2)+"\n")
    shutil.rmtree(upstream)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--native", type=Path, required=True)
    parser.add_argument("--chromium-archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    prepare(args.archive, args.native, args.chromium_archive, args.output)
    print("Frozen Selkies qualification build context prepared.")
