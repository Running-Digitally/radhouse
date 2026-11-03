"""Bounded, credential-free native web collection for owner-approved questions.

Runs separately from the private review model. It receives only public questions,
never the chat, saved commitment, progress, browser profile or worker credentials.
"""
import asyncio
import contextlib
import hashlib
import importlib.util
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.parse import urlsplit


def contract_path():
    adjacent = Path(__file__).with_name('research_contract.py')
    return adjacent if adjacent.is_file() else Path(__file__).parents[2] / 'src/radhouse/domain/research_contract.py'


def load_contract():
    spec = importlib.util.spec_from_file_location('radhouse_public_research_contract', contract_path())
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract = load_contract()
WEB_CONFIG = {'web': {'backend': 'keenable', 'search_backend': 'keenable', 'extract_backend': 'keenable',
    'provider_tier': {'keenable': 'free', 'exa': 'paid', 'parallel': 'paid', 'firecrawl': 'paid'},
    'keyless_fallback': True, 'keyless_rescue': False, 'cache_enabled': False}}


def public_address(url):
    if not contract.public_url(url):
        return False
    try:
        addresses = socket.getaddrinfo(urlsplit(url).hostname, 443, type=socket.SOCK_STREAM)
        return bool(addresses) and all(ipaddress.ip_address(row[4][0]).is_global for row in addresses)
    except (ValueError, OSError):
        return False


def clipped(value, size):
    return value.encode()[:size].decode('utf-8', errors='ignore').strip()


def collect_one(request, search, extract, *, address_check=public_address, clock=time.time):
    result = {'commitment_id': request['commitment_id'], 'provider': contract.PROVIDER,
              'coverage': 'unavailable', 'checked_at': clock(), 'sources': []}
    query = request['query']
    if not isinstance(query, str) or not 5 <= len(query) <= 300 or any(ord(c) < 32 for c in query):
        raise ValueError('invalid_public_question')
    found = json.loads(search(query, limit=3))
    if not found.get('success') or found.get('data', {}).get('served_by') not in {None, contract.PROVIDER}:
        return result
    candidates = {}
    for row in found.get('data', {}).get('web', [])[:3]:
        url = row.get('url')
        if address_check(url):
            candidates[url] = row.get('title') or urlsplit(url).hostname
        if len(candidates) == contract.MAX_SOURCES:
            break
    if not candidates:
        return result
    # Keep our retained prefix before Hermes' own head/tail truncation footer;
    # file-path hints in that footer are not public source evidence.
    pages = json.loads(extract(list(candidates), char_limit=16000)).get('results', [])
    seen = set()
    for page in pages:
        url, content = page.get('url'), page.get('content')
        # Reject redirected identities. No follow-up extraction or model-chosen URLs.
        if url not in candidates or url in seen or page.get('error') or not isinstance(content, str) or not content.strip():
            continue
        text = clipped(content, contract.MAX_TEXT)
        title = clipped(str(page.get('title') or candidates[url]), 200)
        result['sources'].append({'id': contract.source_id(url, text), 'url': url, 'title': title, 'text': text})
        seen.add(url)
    # Search is not exhaustive and page excerpts are bounded. Do not label that
    # complete coverage, even when both requested pages were retrieved.
    if result['sources']:
        result['coverage'] = 'partial'
    result['checked_at'] = clock()
    return result


def native_collect(request, root):
    pins = json.loads(Path(__file__).with_name('research-source-lock.json').read_text())
    for name, expected in pins['files'].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
            raise ValueError('public_research_runtime_unqualified')
    sys.path.insert(0, str(root))
    from tools import web_tools
    from plugins.web.keyless_mcp import _ring_order
    if (web_tools._get_search_backend() != contract.PROVIDER or web_tools._get_extract_backend() != contract.PROVIDER
            or _ring_order(contract.PROVIDER) != [contract.PROVIDER]):
        raise ValueError('public_research_provider_unqualified')
    def extract(urls, **kwargs):
        return asyncio.run(web_tools.web_extract_tool(urls, **kwargs))
    return collect_one(request, web_tools.web_search_tool, extract)


def collect_requests(requests, config, *, run=subprocess.run, clock=time.time):
    if type(requests) is not list or not 1 <= len(requests) <= 3:
        raise ValueError('invalid_research_requests')
    items = []
    for request in requests:
        if type(request) is not dict or set(request) != {'commitment_id', 'query'}:
            raise ValueError('invalid_research_request')
        fallback = {'commitment_id': request['commitment_id'], 'provider': contract.PROVIDER,
                    'coverage': 'unavailable', 'checked_at': clock(), 'sources': []}
        with tempfile.TemporaryDirectory(prefix='radhouse-public-research-') as directory:
            home = Path(directory)
            (home / 'config.yaml').write_text(json.dumps(WEB_CONFIG))
            # No inherited HOME, tokens, proxy, owner config, PYTHONPATH or native
            # plugin directories. JSON is valid YAML; fresh private home is erased.
            env = {'HOME': directory, 'HERMES_HOME': directory, 'PATH': '/usr/bin:/bin',
                   'LANG': 'C.UTF-8', 'PYTHONNOUSERSITE': '1'}
            try:
                response = run([sys.executable, '-I', str(Path(__file__).resolve()), str(Path(config['hermes_root']).resolve())],
                    input=json.dumps(request), text=True, capture_output=True, env=env, cwd=directory, timeout=65, check=False)
                if response.returncode or len(response.stdout.encode()) > 16000:
                    raise ValueError('public_research_failed')
                item = json.loads(response.stdout)
                contract.validate_packet({'items': [item]}, [request], fallback['checked_at'], clock())
            except (ValueError, TypeError, KeyError, OSError, subprocess.TimeoutExpired):
                item = {**fallback, 'checked_at': clock()}
            items.append(item)
    return {'items': items}


def main():
    try:
        request = json.loads(sys.stdin.read(2001))
        with open(os.devnull, 'w') as sink, contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
            result = native_collect(request, Path(sys.argv[1]).resolve())
        print(json.dumps(result))
        return 0
    except Exception:
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
