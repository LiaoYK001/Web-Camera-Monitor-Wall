"""Stage an offline Windows runtime from verified build products and archives."""
import argparse
import hashlib
import json
import os
import pathlib
import shutil
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
DESKTOP = ROOT / "desktop"

def extract(archive, destination):
    with zipfile.ZipFile(archive) as source:
        for item in source.infolist():
            name = pathlib.PurePosixPath(item.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in item.filename or ":" in item.filename or (item.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("unsafe dependency archive member")
        source.extractall(destination)

def copy_tree(source, target):
    shutil.copytree(source, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".git", "node_modules"))

def stage(args):
    output = args.output.resolve()
    if output != (DESKTOP / "runtime").resolve(): raise ValueError("runtime output must be desktop/runtime")
    if output.exists(): raise ValueError("Remove the previous verified staging directory before rebuilding")
    output.mkdir()
    lock = json.loads((DESKTOP / "dependencies.lock.json").read_text())
    unpack = args.cache / "unpacked"
    unpack.mkdir(exist_ok=True)
    for item in lock["artifacts"]:
        archive = args.cache / (item["id"] + ".zip")
        if hashlib.sha256(archive.read_bytes()).hexdigest() != item["sha256"]: raise ValueError(f"dependency checksum failed: {item['id']}")
        destination = unpack / item["id"]
        if destination.exists(): shutil.rmtree(destination)
        extract(archive, destination)
    copy_tree(args.core, output)
    copy_tree(args.obs, output / "obs")
    # No Qt OBS executable is built to trigger its regular dependency bundler.
    obs_bin=output / "obs" / "bin" / "64bit"
    obs_bin.mkdir(parents=True,exist_ok=True)
    for file in (unpack / "obs-deps").rglob("*.dll"):
        if "debug" not in str(file.relative_to(unpack / "obs-deps")).lower():
            target=obs_bin/file.name
            if not target.exists(): shutil.copy2(file,target)
    (output / "bin").mkdir(exist_ok=True)
    for file in (args.vcpkg / "bin").glob("*.dll"): shutil.copy2(file, output / "bin" / file.name)
    for file in (args.obs / "bin" / "64bit").glob("*.exe"): shutil.copy2(file, output / "bin" / file.name)
    openssl = next((args.vcpkg / "tools" / "openssl").rglob("openssl.exe"))
    shutil.copy2(openssl, output / "bin" / "openssl.exe")
    for name in ["go2rtc", "mediamtx", "caddy"]:
        file = next((unpack / name).rglob(name + ".exe")); shutil.copy2(file, output / "bin" / file.name)
    ffmpeg_bin = next((unpack / "ffmpeg").rglob("ffmpeg.exe")).parent
    for file in ffmpeg_bin.iterdir():
        if file.is_file(): shutil.copy2(file, output / "bin" / file.name)
    copy_tree(unpack / "python", output / "python")
    for file in (output / "bin").glob("*.dll"):
        if file.name.lower().startswith(("msvcp", "vcruntime", "concrt")): shutil.copy2(file, output / "python" / file.name)
    site = output / "python" / "Lib" / "site-packages"; site.mkdir(parents=True)
    for name in ["numpy", "onnxruntime"]: copy_tree(unpack / name, site)
    pth = output / "python" / "python312._pth"
    pth.write_text("python312.zip\n.\nLib/site-packages\n../services\nimport site\n", encoding="ascii")
    for name in ["camera", "events", "nvr", "cluster", "v2", "analytics", "archive", "backup"]:
        (output / "services" / name).mkdir(parents=True)
        for file in (ROOT / name).glob("*.py"): shutil.copy2(file, output / "services" / name / file.name)
    shutil.copy2(ROOT / "runtime_support.py", output / "services" / "runtime_support.py")
    (output / "services" / "scripts").mkdir(); shutil.copy2(ROOT / "scripts" / "hardware-probe.py", output / "services" / "scripts" / "hardware-probe.py")
    (output / "services" / "go2rtc").mkdir(); shutil.copy2(ROOT / "go2rtc" / "runtime.py", output / "services" / "go2rtc" / "runtime.py")
    copy_tree(DESKTOP / "python", output / "services" / "desktop-tools")
    copy_tree(ROOT / "web" / "dist", output / "web"); copy_tree(ROOT / "web" / "go2rtc-dist", output / "go2rtc-www")
    (output / "etc").mkdir(); shutil.copy2(ROOT / "gateway" / "mediamtx.yml", output / "etc" / "mediamtx.yml"); shutil.copy2(ROOT / "go2rtc" / "go2rtc.yaml", output / "etc" / "go2rtc.yaml")
    licenses = output / "licenses"; licenses.mkdir()
    for name in ["go2rtc","mediamtx","caddy","ffmpeg","python"]:
        target=licenses/name;target.mkdir()
        for file in (unpack/name).rglob("*"):
            if file.is_file() and (any(word in file.name.lower() for word in ["license","copying","notice"]) or file.suffix in [".md", ".txt"]):
                relative=file.relative_to(unpack/name);(target/relative).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target/relative)
    copy_tree(args.vcpkg / "share", licenses / "vcpkg")
    shutil.copy2(ROOT / "LICENSE", licenses / "WEBobs-LICENSE"); shutil.copy2(ROOT / "obs" / "obs-studio" / "COPYING", licenses / "OBS-COPYING")
    for name in ["obs-deps","obs-qt","obs-cef"]:
        target=licenses/name;target.mkdir()
        for file in (unpack/name).rglob("*"):
            if file.is_file() and any(word in file.name.lower() for word in ["license","copying","notice"]):
                relative=file.relative_to(unpack/name);(target/relative).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(file,target/relative)
    (licenses/"THIRD-PARTY-NOTICES.md").write_text("# Bundled components\n\n"+"\n".join(f"- {item['id']} {item['version']} — {item['license']} — {item['url']}" for item in lock['artifacts'])+"\n\nOBS and WebOBS corresponding source are supplied with the release. FFmpeg build identity and build configuration are retained; official publication additionally requires reviewed matching third-party source archives.\n",encoding="utf-8")
    shutil.copy2(DESKTOP / "dependencies.lock.json", licenses / "dependencies.lock.json")
    # Keep all dynamic runtime DLLs; exclude only build metadata and debug symbols.
    for file in list(output.rglob("*.pdb")): file.unlink()
    for directory in [output/"obs"/"include",output/"obs"/"lib",output/"obs"/"cmake"]:
        if directory.exists(): shutil.rmtree(directory)

if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    for field in ["cache","core","obs","vcpkg","output"]: parser.add_argument("--"+field,required=True,type=pathlib.Path)
    stage(parser.parse_args())
