#!/usr/bin/env python3
"""Install pinned website extractors and Node without system pip/PATH at runtime."""
import argparse
import hashlib
import json
import re
from pathlib import Path, PurePosixPath
import shutil
import tarfile
import tempfile
import time
import urllib.request
import zipfile


def safe_member(name):
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name:
        raise ValueError('unsafe online-source archive member')
    return path


def verified_download(item, cache):
    cache.mkdir(parents=True, exist_ok=True)
    filename = safe_member(item['filename'])
    if len(filename.parts) != 1:
        raise ValueError('invalid locked filename')
    target = cache / filename.name
    if target.is_file() and not target.is_symlink():
        with target.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() == item['sha256']:
                return target
    for attempt in range(4):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=cache, delete=False) as output:
                temporary = Path(output.name)
                with urllib.request.urlopen(item['url'], timeout=30) as response:
                    size = 0
                    while block := response.read(65536):
                        size += len(block)
                        if size > 256 * 1024 * 1024:
                            raise ValueError('online-source artifact exceeds download limit')
                        output.write(block)
            with temporary.open('rb') as stream:
                if hashlib.file_digest(stream, 'sha256').hexdigest() != item['sha256']:
                    raise ValueError('online-source artifact checksum mismatch')
            if 'size' in item and temporary.stat().st_size != item['size']:
                raise ValueError('online-source artifact size mismatch')
            temporary.replace(target)
            return target
        except OSError:
            if attempt == 3:
                raise RuntimeError('could not download locked online-source dependency') from None
            time.sleep(1 + attempt)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()


def install(lock_path, platform, cache, site, binary, licenses):
    lock = json.loads(lock_path.read_text(encoding='utf-8'))
    if lock['schemaVersion'] != 1 or platform not in lock['platforms']:
        raise ValueError('unsupported online-source platform lock')
    chosen = lock['platforms'][platform]
    site.mkdir(parents=True, exist_ok=True)
    binary.mkdir(parents=True, exist_ok=True)
    licenses.mkdir(parents=True, exist_ok=True)
    for item in chosen['wheels']:
        if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', item['name']) or not re.fullmatch(r'[a-f0-9]{64}', item['sha256']):
            raise ValueError('invalid online-source package lock')
        archive = verified_download(item, cache)
        with zipfile.ZipFile(archive) as source:
            if sum(member.file_size for member in source.infolist()) > 256 * 1024 * 1024:
                raise ValueError('online-source wheel exceeds expansion limit')
            for member in source.infolist():
                relative = safe_member(member.filename)
                if (member.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError('online-source wheel contains symbolic link')
                parts = relative.parts
                if parts and parts[0].endswith('.data'):
                    if len(parts) < 3 or parts[1] not in ('purelib', 'platlib'):
                        continue # CLI scripts are replaced by the product's fixed entry.
                    relative = PurePosixPath(*parts[2:])
                target = site.joinpath(*relative.parts)
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(member) as incoming, target.open('wb') as output:
                        shutil.copyfileobj(incoming, output, 65536)
                    if '.dist-info/' in member.filename and any(word in member.filename.lower() for word in ('license', 'copying', 'notice')):
                        notice = licenses / item['name'] / relative
                        notice.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(target, notice)
    node = chosen['node']
    archive = verified_download(node, cache)
    if platform == 'windows-x64':
        with zipfile.ZipFile(archive) as source:
            for name in ('node.exe', 'LICENSE'):
                members = [member for member in source.infolist() if len(safe_member(member.filename).parts) == 2 and safe_member(member.filename).name == name]
                if len(members) != 1 or members[0].is_dir() or (members[0].external_attr >> 16) & 0o170000 == 0o120000 or members[0].file_size > 256 * 1024 * 1024:
                    raise ValueError('invalid locked Node archive')
                target = binary / name if name == 'node.exe' else licenses / 'Node-LICENSE'
                with source.open(members[0]) as incoming, target.open('wb') as output:
                    shutil.copyfileobj(incoming, output, 65536)
    else:
        with tarfile.open(archive, 'r:xz') as source:
            for suffix, target in (('bin/node', binary / 'node'), ('LICENSE', licenses / 'Node-LICENSE')):
                members = [member for member in source.getmembers() if member.name.split('/', 1)[-1] == suffix]
                if len(members) != 1 or not members[0].isfile() or members[0].size > 256 * 1024 * 1024:
                    raise ValueError('invalid locked Node archive')
                with source.extractfile(members[0]) as incoming, target.open('wb') as output:
                    shutil.copyfileobj(incoming, output, 65536)
            (binary / 'node').chmod(0o755)
    shutil.copy2(lock_path, licenses / 'online-source-dependencies.lock.json')
    print('Installed verified yt-dlp, Streamlink and Node runtime for ' + platform, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for field in ('lock', 'cache', 'site', 'bin', 'licenses'):
        parser.add_argument('--' + field, type=Path, required=True)
    parser.add_argument('--platform', choices=('linux-x64', 'windows-x64'), required=True)
    args = parser.parse_args()
    install(args.lock, args.platform, args.cache, args.site, args.bin, args.licenses)
