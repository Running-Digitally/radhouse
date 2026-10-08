"""Disposable bounded reader. Uploaded text, links and formulas are never run."""
import base64
from bisect import bisect_left, bisect_right
from dataclasses import dataclass
from io import BytesIO, TextIOWrapper
import hashlib
import json
import os
from pathlib import Path
import re
import resource
import stat
import sys
from urllib.parse import quote, unquote
from xml.etree import ElementTree as ET
from zipfile import ZipFile

CHUNK_CHARS = 2048
MAX_SCAN_UNITS = 16_384
MAX_TEXT_BYTES = 24 * 1024
MAX_PASSAGES = 8


@dataclass(frozen=True)
class Fragment:
    base: str
    label: str
    offset: int
    text: str
    checkpoint: dict | None = None

    @property
    def locator(self):
        return f"{self.base}:offset:{self.offset}"


def _chunks(base, label, text):
    if not text:
        yield Fragment(base, label, 0, "")
    for offset in range(0, len(text), CHUNK_CHARS):
        yield Fragment(base, label, offset, text[offset:offset + CHUNK_CHARS])


def _local(node):
    return node.tag.rsplit("}", 1)[-1]


class _SafeXML:
    def __init__(self, stream):
        self.stream, self.tail = stream, b""

    def read(self, size=-1):
        data = self.stream.read(size)
        check = (self.tail + data).replace(b"\x00", b"").upper()
        if b"<!DOCTYPE" in check or b"<!ENTITY" in check:
            raise ValueError("document_unreadable")
        self.tail = check[-32:]
        return data


def _xml(archive, path):
    with archive.open(path) as stream:
        return ET.parse(_SafeXML(stream)).getroot()


def _relationship_targets(archive, path, prefix, kind, *, ignored_types=()):
    result, seen = {}, set()
    for node in _xml(archive, path):
        identity = node.attrib.get("Id")
        if not identity or identity in seen:
            raise ValueError("document_unreadable")
        seen.add(identity)
        if node.attrib.get("TargetMode") == "External":
            continue
        relation_type = node.attrib.get("Type", "")
        if relation_type and not relation_type.endswith("/" + kind):
            if any(relation_type.endswith("/" + ignored) for ignored in ignored_types):
                result[identity] = None
            continue
        target = _internal_target(node, prefix, kind)
        result[identity] = target
    return result


def _word_text(node):
    name = _local(node)
    if name in {"del", "moveFrom"}:
        return ""
    if name == "t":
        return node.text or ""
    if name == "tab":
        return "\t"
    if name in {"br", "cr"}:
        return "\n"
    return "".join(_word_text(child) for child in node)


def _word(archive):
    with archive.open("word/document.xml") as stream:
        stack, number = [], 0
        for event, node in ET.iterparse(_SafeXML(stream), events=("start", "end")):
            name = _local(node)
            if event == "start":
                stack.append(name)
                continue
            if name == "p":
                if not set(stack[:-1]) & {"del", "moveFrom"}:
                    number += 1
                    yield from _chunks(f"word:paragraph:{number}", f"Paragraph {number}", _word_text(node))
                node.clear()
            stack.pop()


def _sheets(archive):
    targets = _relationship_targets(archive, "xl/_rels/workbook.xml.rels", "xl/", "worksheet",
                                    ignored_types=("chartsheet",))
    strings = _shared_strings(archive)
    workbook = _xml(archive, "xl/workbook.xml")
    sheet_names = set()
    for sheet in workbook.iter():
        if _local(sheet) != "sheet":
            continue
        name = sheet.attrib.get("name", "")
        if not name or len(name.encode()) > 512 or name in sheet_names:
            raise ValueError("document_unreadable")
        sheet_names.add(name)
        identity = next((value for key, value in sheet.attrib.items() if key.endswith("}id")), None)
        path = targets.get(identity)
        if identity in targets and path is None:
            continue
        if not path:
            raise ValueError("document_unreadable")
        yield from _sheet_fragments(archive, path, name, strings)


def _slides(archive, selected=None):
    targets = _relationship_targets(archive, "ppt/_rels/presentation.xml.rels", "ppt/", "slide")
    number = 0
    for slide in _xml(archive, "ppt/presentation.xml").iter():
        if _local(slide) != "sldId":
            continue
        number += 1
        if selected is not None and selected != f"slide:{number}":
            continue
        identity = next((value for key, value in slide.attrib.items() if key.endswith("}id")), None)
        if identity not in targets:
            raise ValueError("document_unreadable")
        root = _xml(archive, targets[identity])
        text = "\n".join(n.text or "" for n in root.iter() if _local(n) == "t")
        yield from _chunks(f"slide:{number}", f"Slide {number}", text)
        if selected is not None:
            return
    if selected is not None:
        raise ValueError("document_locator_not_found")


def _text_source(data):
    if isinstance(data, Path):
        return data.open("rb")
    if isinstance(data, bytes):
        return BytesIO(data)
    return os.fdopen(os.dup(data.fileno()), "rb")


def _fragments(data, extension, resume=None, selected=None):
    if extension == ".txt":
        yield from _text_fragments(data, resume)
        return
    if extension == ".pdf":
        yield from _pdf_fragments(data, selected)
        return
    if extension not in {".docx", ".xlsx", ".pptx"}:
        raise ValueError("document_unreadable")
    with ZipFile(BytesIO(data) if isinstance(data, bytes) else data) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or any("vbaproject" in n.lower() for n in names):
            raise ValueError("document_unreadable")
        if any(entry.flag_bits & 1 for entry in archive.infolist()):
            raise ValueError("document_encrypted")
        if extension == ".pptx":
            yield from _slides(archive, selected)
        else:
            yield from {".docx": _word, ".xlsx": _sheets}[extension](archive)


def _selection(locator):
    if locator is None:
        return None, 0
    base, separator, offset_text = locator.rpartition(":offset:")
    if not separator:
        base, offset_text = locator, "0"
    if not re.fullmatch(r"0|[1-9]\d*", offset_text, re.ASCII):
        raise ValueError("document_locator_not_found")
    prefixes = ("text:line:", "pdf:page:", "word:paragraph:", "slide:")
    prefix = next((item for item in prefixes if base.startswith(item)), None)
    if prefix is not None:
        valid = re.fullmatch(r"[1-9]\d*", base[len(prefix):], re.ASCII)
    else:
        valid = re.fullmatch(r"sheet:[^:]+:cell:[A-Z]{1,3}[1-9]\d{0,6}", base, re.ASCII)
    if not valid:
        raise ValueError("document_locator_not_found")
    offset = int(offset_text)
    if base.startswith("sheet:"):
        encoded = base.split(":")[1]
        if quote(unquote(encoded), safe="") != encoded:
            raise ValueError("document_locator_not_found")
    return base, offset


def _match_span(text, needle, minimum_end):
    """Map casefold expansions back to character offsets, skipping old hits."""
    folded = text.casefold()
    boundaries = [0]
    for character in text:
        boundaries.append(boundaries[-1] + len(character.casefold()))
    position = folded.find(needle)
    while position >= 0:
        begin = bisect_right(boundaries, position) - 1
        end = bisect_left(boundaries, position + len(needle))
        if end > minimum_end:
            return begin, end
        position = folded.find(needle, position + 1)
    return None


class _PassageScan:
    """State of one bounded reader pass; continuations retain exact offsets."""

    def __init__(self, request):
        self.request = request
        self.search = request["operation"] == "search"
        self.selected, self.selected_offset = _selection(request["locator"])
        self.needle = request["query"].casefold() if self.search else None
        self.overlap = max(0, len(self.needle) - 1) if self.search else 0
        self.position = request["position"]
        self.resume = request.get("resume")
        self.passages, self.output_bytes, self.scanned = [], 0, 0
        self.previous, self.tail = None, ""
        self.any_text = bool(self.resume and self.resume["has_text"])
        self.selected_found, self.selected_offset_found = False, False

    def complete(self):
        return {"passages": self.passages, "next_position": None, "complete": True}

    def continuation(self, next_position, prior):
        checkpoint = {**prior.checkpoint, "has_text": self.any_text} if prior and prior.checkpoint else None
        return {"passages": self.passages, "next_position": next_position, "next_resume": checkpoint, "complete": False}

    def require_text(self):
        if not self.any_text:
            raise ValueError("document_needs_ocr" if self.request["extension"] == ".pdf" else "document_unreadable")

    def require_selected_offset(self):
        if not self.selected_offset_found:
            raise ValueError("document_locator_not_found")

    def combine(self, fragment):
        previous = self.previous
        contiguous = previous is not None and previous.base == fragment.base and previous.offset + len(previous.text) == fragment.offset
        prefix = self.tail if contiguous else ""
        combined = prefix + fragment.text
        self.previous = fragment
        self.tail = combined[-self.overlap:] if self.overlap else ""
        return prefix, combined

    def select_fragment(self, fragment, index):
        if self.selected is None or fragment.base == self.selected:
            self.any_text = self.any_text or bool(fragment.text.strip())
        if index < self.position:
            return "skip"
        if self.selected is not None and fragment.base != self.selected:
            if self.selected_found:
                self.require_selected_offset()
                self.require_text()
                return "complete"
            return "skip"
        if self.selected is not None:
            self.selected_found = True
            if fragment.offset + len(fragment.text) <= self.selected_offset and fragment.text:
                return "skip"
            self.selected_offset_found = not fragment.text and self.selected_offset == 0 or self.selected_offset < fragment.offset + len(fragment.text)
        return "scan"

    def passage(self, fragment, prefix, combined):
        if self.search:
            found = _match_span(combined, self.needle, len(prefix))
            if found is None:
                text = None
            else:
                begin = max(0, found[0] - 160)
                text = combined[begin: max(found[1] + 160, begin + 512)]
                start = fragment.offset - len(prefix) + begin
        else:
            start = max(fragment.offset, self.selected_offset if self.selected is not None else 0)
            text = fragment.text[start - fragment.offset:]
        passage = {"locator": f"{fragment.base}:offset:{start}", "label": fragment.label, "text": text} if text else None
        cost = len(json.dumps(passage, ensure_ascii=False).encode()) if passage else 0
        return passage, cost

    def after_limit(self, fragments, index, fragment):
        try:
            following = next(fragments)
        except StopIteration:
            return self.complete()
        if self.selected is not None and following.base != self.selected:
            return self.complete()
        return self.continuation(index + 1, fragment)


    def record_passage(self, passage, cost):
        if cost and self.output_bytes + cost > MAX_TEXT_BYTES:
            return False
        if passage and passage["text"].strip():
            self.passages.append(passage)
            self.output_bytes += cost
        return True


    def run(self, data):
        fragments = iter(_fragments(data, self.request["extension"], self.resume, self.selected))
        for index, fragment in enumerate(fragments, self.resume["index"] if self.resume else 0):
            prior = self.previous
            prefix, combined = self.combine(fragment)
            disposition = self.select_fragment(fragment, index)
            if disposition == "skip":
                continue
            if disposition == "complete":
                return self.complete()
            self.scanned += 1
            passage, cost = self.passage(fragment, prefix, combined)
            if not self.record_passage(passage, cost):
                return self.continuation(index, prior)
            if len(self.passages) == MAX_PASSAGES or self.scanned == MAX_SCAN_UNITS:
                return self.after_limit(fragments, index, fragment)
        if self.selected is not None and (not self.selected_found or not self.selected_offset_found):
            raise ValueError("document_locator_not_found")
        self.require_text()
        return self.complete()


def _operate(data, request):
    return _PassageScan(request).run(data)


def _source_identity(source):
    state = os.fstat(source.fileno())
    if not stat.S_ISREG(state.st_mode):
        raise ValueError("document_source_changed")
    return state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns


def _verified_operate(request):
    """Verify and consume the same source under the child's existing budgets."""
    expected = request["sha256"]
    if "source_fd" not in request:
        data = base64.b64decode(request["data"], validate=True)
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("document_source_changed")
        return _operate(data, request)
    with os.fdopen(os.dup(request["source_fd"]), "rb") as source:
        identity = _source_identity(source)
        if hashlib.file_digest(source, "sha256").hexdigest() != expected or _source_identity(source) != identity:
            raise ValueError("document_source_changed")
        source.seek(0)
        value = _operate(source, request)
        # Replacing the pathname cannot redirect this descriptor. In-place writes
        # during hashing/parsing invalidate every passage, including same-size
        # writes with a restored mtime (ctime still changes).
        if _source_identity(source) != identity:
            raise ValueError("document_source_changed")
        return value


def _main():
    resource.setrlimit(resource.RLIMIT_CPU, (10, 10))
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0, 0))
    try:
        request = json.load(sys.stdin)
        value = _verified_operate(request)
        encoded = json.dumps(value, ensure_ascii=False)
        if len(encoded.encode()) > 32 * 1024:
            raise ValueError("document_operation_exhausted")
        print(encoded)
    except Exception as exc:
        from .document_access import _ERRORS
        code = str(exc) if isinstance(exc, ValueError) and str(exc) in _ERRORS else "document_unreadable"
        print(json.dumps({"error": code}))


def _internal_target(node, prefix, kind):
    target = node.attrib.get("Target", "")
    target = target.lstrip("/") if target.startswith("/" + prefix) else prefix + target
    if not re.fullmatch(re.escape(prefix + kind + "s/") + r"[^/\\?#]+\.xml", target) or ".." in target:
        raise ValueError("document_unreadable")
    return target


def _shared_strings(archive):
    strings = []
    if "xl/sharedStrings.xml" in archive.namelist():
        with archive.open("xl/sharedStrings.xml") as stream:
            for _, node in ET.iterparse(_SafeXML(stream)):
                if _local(node) == "si":
                    strings.append("".join(n.text or "" for n in node.iter() if _local(n) == "t"))
                    node.clear()
    return strings


def _cell_value(cell, strings):
    value = next((n.text or "" for n in cell if _local(n) == "v"), "")
    kind = cell.attrib.get("t")
    if kind == "s":
        if not value.isascii() or not value.isdigit() or int(value) >= len(strings):
            raise ValueError("document_unreadable")
        value = strings[int(value)]
    elif kind == "inlineStr":
        value = "".join(n.text or "" for n in cell.iter() if _local(n) == "t")
    formula = next((n.text for n in cell if _local(n) == "f"), None)
    if formula is not None:
        value += f" [cached value; formula: {formula}]"
    return value


def _sheet_fragments(archive, path, name, strings):
    seen = set()
    with archive.open(path) as stream:
        for _, cell in ET.iterparse(_SafeXML(stream)):
            if _local(cell) != "c":
                continue
            reference = cell.attrib.get("r", "")
            if not re.fullmatch(r"[A-Z]{1,3}[1-9]\d{0,6}", reference, re.ASCII) or reference in seen:
                raise ValueError("document_unreadable")
            seen.add(reference)
            value = _cell_value(cell, strings)
            yield from _chunks(f"sheet:{quote(name, safe='')}:cell:{reference}", f"{name}!{reference}", value)
            cell.clear()


def _text_fragments(data, resume):
    # Duplicate an already verified descriptor so TextIOWrapper can close its
    # own stream without losing the source identity used by the final check.
    with _text_source(data) as raw:
        with TextIOWrapper(raw, encoding="utf-8-sig", errors="strict", newline=None) as stream:
            line, offset, index = 1, 0, 0
            if resume is not None:
                stream.seek(resume["cookie"])
                line, offset, index = resume["line"], resume["offset"], resume["index"]
            while True:
                cookie = stream.tell()
                text = stream.readline(CHUNK_CHARS)
                if not text:
                    break
                if any(ord(c) < 32 and c not in "\n\r\t" for c in text):
                    raise ValueError("document_unreadable")
                yield Fragment(f"text:line:{line}", f"Line {line}", offset, text,
                               {"cookie": cookie, "line": line, "offset": offset, "index": index})
                index += 1
                offset += len(text)
                if text.endswith("\n"):
                    line, offset = line + 1, 0
    return


def _pdf_fragments(data, selected):
    if selected is not None and not selected.startswith("pdf:page:"):
        raise ValueError("document_locator_not_found")
    from pypdf import PdfReader
    reader = PdfReader(BytesIO(data) if isinstance(data, bytes) else data, strict=True)
    if reader.is_encrypted:
        raise ValueError("document_encrypted")
    if selected is not None:
        number = int(selected.removeprefix("pdf:page:"))
        if number > len(reader.pages):
            raise ValueError("document_locator_not_found")
        page = reader.pages[number - 1]
        yield from _chunks(selected, f"Page {number}", page.extract_text() or "")
        return
    for number, page in enumerate(reader.pages, 1):
        yield from _chunks(f"pdf:page:{number}", f"Page {number}", page.extract_text() or "")
    return


if __name__ == "__main__":
    _main()
