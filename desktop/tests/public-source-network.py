#!/usr/bin/env python3
"""Bounded public-site evidence; never emit signed media URLs or raw errors."""
import argparse
import json
from pathlib import Path
import ssl
import sys
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
SOURCES = {
    'reported': 'https://www.youtube.com/watch?v=eYDDvvGbhp8',
    'dw': 'https://www.youtube.com/@DWNews/live',
    'aljazeera': 'https://www.youtube.com/@AlJazeeraEnglish/live',
}


def tls_probe(host, context):
    result = {'host': host, 'certificateVerification': True}
    try:
        with urllib.request.urlopen('https://' + host + '/', context=context, timeout=10) as response:
            result.update(tls='verified', status=response.status)
    except urllib.error.HTTPError as error:
        result.update(tls='verified', status=error.code)
    except Exception as error:
        result.update(result='failed', errorType=type(error).__name__, eof='EOF' in str(error))
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--runtime', required=True)
    parser.add_argument('--receipt', required=True)
    args = parser.parse_args()
    runtime = Path(args.runtime).resolve()
    sys.path.insert(0, str(runtime / 'python/Lib/site-packages'))
    import certifi
    from yt_dlp import YoutubeDL
    from yt_dlp.globals import plugin_dirs
    plugin_dirs.value = []
    context = ssl.create_default_context(cafile=certifi.where())
    receipt = {'tls': [tls_probe(host, context) for host in ('www.youtube.com', 'manifest.googlevideo.com')], 'sources': []}
    for name, address in SOURCES.items():
        categories = set()

        class Quiet:
            def debug(self, *_): pass
            def info(self, *_): pass
            def warning(self, message, *_):
                for label, needle in [('tls-eof', 'EOF'), ('manifest', 'm3u8'), ('http403', '403'),
                                      ('http429', '429'), ('format', 'format')]:
                    if needle.lower() in str(message).lower():
                        categories.add(label)
            error = warning

        item = {'name': name}
        try:
            with YoutubeDL(dict(quiet=True, no_warnings=True, logger=Quiet(), noplaylist=True,
                                skip_download=True, cachedir=False, socket_timeout=15, retries=1,
                                extractor_retries=1, ignore_no_formats_error=True,
                                ffmpeg_location=str(runtime / 'bin/ffmpeg.exe'),
                                js_runtimes={'node': {'path': str(runtime / 'bin/node.exe')}}, remote_components=set(),
                                format='bv*[height<=720][vcodec^=avc1]+ba[acodec^=mp4a]/b[height<=720][vcodec^=avc1]/bv*[height<=720]+ba/b[height<=720]/b')) as extractor:
                info = extractor.extract_info(address, download=False)
            item.update(isLive=info.get('is_live'), liveStatus=info.get('live_status'),
                        formatCount=len(info.get('formats') or []))
        except Exception as error:
            item.update(result='failed', errorType=type(error).__name__)
        item['warningCategories'] = sorted(categories)
        receipt['sources'].append(item)
    Path(args.receipt).write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt))


if __name__ == '__main__':
    main()
