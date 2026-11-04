"""Bounded public research evidence; no provider, credentials or action authority."""
import hashlib
import json
import math
import re
from urllib.parse import urlsplit

MAX_SOURCES = 2
MAX_TEXT = 3000
PROVIDER = 'keenable'


def public_url(value):
    if not isinstance(value, str) or len(value) > 1500 or any(c.isspace() or ord(c) < 32 for c in value):
        return False
    try:
        url = urlsplit(value)
        host = url.hostname or ''
        return (url.scheme == 'https' and url.port in {None, 443} and not url.username
                and not url.password and not url.query and not url.fragment and '\\' not in value
                and re.fullmatch(r'(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,63}', host) is not None
                and not host.lower().endswith(('.local', '.localhost', '.internal', '.test', '.invalid', '.example')))
    except ValueError:
        return False


def source_id(url, text):
    return hashlib.sha256((url + '\0' + text).encode()).hexdigest()


def source_set_hash(sources):
    return hashlib.sha256(json.dumps(sorted(s['id'] for s in sources)).encode()).hexdigest()


def requests(snapshot):
    return [{'commitment_id': i['id'], 'query': i['research_query']}
            for i in snapshot.get('followups', []) if i.get('research_query')]


def validate_packet(value, expected, earliest, latest):
    if type(value) is not dict or set(value) != {'items'} or type(value['items']) is not list:
        raise ValueError('invalid_research_evidence')
    identifiers = {item['commitment_id'] for item in expected}
    if len(value['items']) != len(identifiers):
        raise ValueError('incomplete_research_evidence')
    seen = set()
    for item in value['items']:
        _validate_item(item, earliest, latest)
        if item['commitment_id'] not in identifiers or item['commitment_id'] in seen:
            raise ValueError('research_identity_mismatch')
        seen.add(item['commitment_id'])
    return value


def _validate_item(item, earliest, latest):
    if type(item) is not dict or set(item) != {'commitment_id', 'coverage', 'sources', 'checked_at', 'provider'}:
        raise ValueError('invalid_research_evidence')
    if item['provider'] != PROVIDER or item['coverage'] not in {'available', 'partial', 'unavailable'}:
        raise ValueError('invalid_research_coverage')
    checked = item['checked_at']
    if type(checked) not in {int, float} or not math.isfinite(checked) or not earliest <= checked <= latest + 5:
        raise ValueError('invalid_research_time')
    sources = item['sources']
    if type(sources) is not list or len(sources) > MAX_SOURCES:
        raise ValueError('invalid_research_sources')
    if bool(sources) == (item['coverage'] == 'unavailable'):
        raise ValueError('invalid_research_coverage')
    seen = set()
    for source in sources:
        _validate_source(source, seen)
        seen.add(source['url'])


def _validate_source(source, seen):
    if type(source) is not dict or set(source) != {'id', 'url', 'title', 'text'}:
        raise ValueError('invalid_research_source')
    if not public_url(source['url']):
        raise ValueError('public_url_required')
    if any(not isinstance(source[k], str) or not source[k].strip() or len(source[k]) > limit
           for k, limit in [('title', 200), ('text', MAX_TEXT)]):
        raise ValueError('invalid_research_text')
    if source['id'] != source_id(source['url'], source['text']) or source['url'] in seen:
        raise ValueError('invalid_research_source_identity')


def citations(result, evidence):
    values = result.get('citations', [])
    if type(values) is not list or len(values) > MAX_SOURCES:
        raise ValueError('invalid_research_citations')
    sources = {s['id']: s for s in evidence.get('sources', [])} if evidence else {}
    resolved, seen = [], set()
    for citation in values:
        if type(citation) is not dict or set(citation) != {'source_id', 'quote'}:
            raise ValueError('invalid_research_citation')
        identifier, quote = citation['source_id'], citation['quote']
        if (identifier not in sources or identifier in seen or not isinstance(quote, str)
                or not 20 <= len(quote) <= 400 or quote not in sources[identifier]['text']):
            raise ValueError('unverified_research_citation')
        source = sources[identifier]
        resolved.append({'source_id': identifier, 'title': source['title'], 'url': source['url'],
                         'quote': quote, 'retrieved_at': evidence['checked_at']})
        seen.add(identifier)
    if result['action'] == 'quiet' and values:
        raise ValueError('quiet_result_has_citations')
    if evidence:
        _check_reference_identifiers(result, [sources[item['source_id']] for item in values], evidence.get('question', ''))
    return resolved


def _check_reference_identifiers(result, sources, question):
    # An exact quotation does not validate unrelated details the model adds.
    # Reject invented dotted standard/version identifiers and URL references.
    # This is a bounded check, not a claim of general semantic verification.
    text = result.get('reason', '') + '\n' + result.get('preparation', '')
    supported = '\n'.join(source['text'] + '\n' + source['url'] for source in sources)
    pattern = r'\b\d+(?:\.\d+)+\b|https?://[^\s<>")]+'
    references = {value.rstrip('.,;:') for value in re.findall(pattern, text, flags=re.ASCII)}
    supported_references = {value.rstrip('.,;:') for value in re.findall(pattern, supported, flags=re.ASCII)}
    # The owner may ask about a version absent from the returned excerpt. A
    # caveat such as "this does not establish the current 2.2 requirement" must
    # remain expressible. The trusted snapshot supplies this question, never
    # the model or collector. It identifies scope, not factual corroboration.
    supported_references.update(re.findall(r'\b\d+(?:\.\d+)+\b', question, flags=re.ASCII))
    if not references.issubset(supported_references):
        raise ValueError('unsupported_research_reference')
