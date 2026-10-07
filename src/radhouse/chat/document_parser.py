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
        target = node.attrib.get("Target", "")
        target = target.lstrip("/") if target.startswith("/" + prefix) else prefix + target
        if not re.fullmatch(re.escape(prefix + kind + "s/") + r"[^/\\?#]+\.xml", target) or ".." in target:
            raise ValueError("document_unreadable")
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
    strings = []
    if "xl/sharedStrings.xml" in archive.namelist():
        with archive.open("xl/sharedStrings.xml") as stream:
            for _, node in ET.iterparse(_SafeXML(stream)):
                if _local(node) == "si":
                    strings.append("".join(n.text or "" for n in node.iter() if _local(n) == "t"))
                    node.clear()
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
        seen = set()
        with archive.open(path) as stream:
            for _, cell in ET.iterparse(_SafeXML(stream)):
                if _local(cell) != "c":
                    continue
                reference = cell.attrib.get("r", "")
                if not re.fullmatch(r"[A-Z]{1,3}[1-9][0-9]{0,6}", reference) or reference in seen:
                    raise ValueError("document_unreadable")
                seen.add(reference)
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
                yield from _chunks(f"sheet:{quote(name, safe='')}:cell:{reference}", f"{name}!{reference}", value)
                cell.clear()


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


def _fragments(data, extension, resume=None, selected=None):
    if extension == ".txt":
        # Duplicate an already verified descriptor so TextIOWrapper can close its
        # own stream without losing the source identity used by the final check.
        with (data.open("rb") if isinstance(data, Path) else BytesIO(data) if isinstance(data, bytes)
              else os.fdopen(os.dup(data.fileno()), "rb")) as raw:
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
    if extension == ".pdf":
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
    match = re.fullmatch(r"(text:line:[1-9][0-9]*|pdf:page:[1-9][0-9]*|word:paragraph:[1-9][0-9]*|slide:[1-9][0-9]*|sheet:[^:]+:cell:[A-Z]{1,3}[1-9][0-9]{0,6})(?::offset:(0|[1-9][0-9]*))?", locator)
    if not match:
        raise ValueError("document_locator_not_found")
    base, offset = match.group(1), int(match.group(2) or "0")
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


def _operate(data, request):
    search = request["operation"] == "search"
    selected, selected_offset = _selection(request["locator"])
    needle = request["query"].casefold() if search else None
    overlap = max(0, len(needle) - 1) if search else 0
    position = request["position"]
    resume = request.get("resume")
    fragments = iter(_fragments(data, request["extension"], resume, selected))
    passages, output_bytes, scanned = [], 0, 0
    previous, tail = None, ""
    any_text, selected_found, selected_offset_found = bool(resume and resume["has_text"]), False, False

    def continuation(next_position, prior):
        checkpoint = {**prior.checkpoint, "has_text": any_text} if prior and prior.checkpoint else None
        return {"passages": passages, "next_position": next_position, "next_resume": checkpoint, "complete": False}

    for index, fragment in enumerate(fragments, resume["index"] if resume else 0):
        prior = previous
        contiguous = previous is not None and previous.base == fragment.base and previous.offset + len(previous.text) == fragment.offset
        prefix = tail if contiguous else ""
        combined = prefix + fragment.text
        previous, tail = fragment, combined[-overlap:] if overlap else ""
        if selected is None or fragment.base == selected:
            any_text = any_text or bool(fragment.text.strip())
        if index < position:
            continue
        if selected is not None and fragment.base != selected:
            if selected_found:
                if not selected_offset_found:
                    raise ValueError("document_locator_not_found")
                if not any_text:
                    raise ValueError("document_needs_ocr" if request["extension"] == ".pdf" else "document_unreadable")
                return {"passages": passages, "next_position": None, "complete": True}
            continue
        if selected is not None:
            selected_found = True
            if fragment.offset + len(fragment.text) <= selected_offset and fragment.text:
                continue
            selected_offset_found = not fragment.text and selected_offset == 0 or selected_offset < fragment.offset + len(fragment.text)
        scanned += 1
        if search:
            found = _match_span(combined, needle, len(prefix))
            if found is None:
                text = None
            else:
                begin = max(0, found[0] - 160)
                text = combined[begin: max(found[1] + 160, begin + 512)]
                start = fragment.offset - len(prefix) + begin
        else:
            start = max(fragment.offset, selected_offset if selected is not None else 0)
            text = fragment.text[start - fragment.offset:]
        passage = {"locator": f"{fragment.base}:offset:{start}", "label": fragment.label, "text": text} if text else None
        cost = len(json.dumps(passage, ensure_ascii=False).encode()) if passage else 0
        if cost and output_bytes + cost > MAX_TEXT_BYTES:
            return continuation(index, prior)
        if text and text.strip():
            passages.append(passage)
            output_bytes += cost
        if len(passages) == MAX_PASSAGES or scanned == MAX_SCAN_UNITS:
            try:
                following = next(fragments)
            except StopIteration:
                return {"passages": passages, "next_position": None, "complete": True}
            if selected is not None and following.base != selected:
                return {"passages": passages, "next_position": None, "complete": True}
            return continuation(index + 1, fragment)
    if selected is not None and (not selected_found or not selected_offset_found):
        raise ValueError("document_locator_not_found")
    if not any_text:
        raise ValueError("document_needs_ocr" if request["extension"] == ".pdf" else "document_unreadable")
    return {"passages": passages, "next_position": None, "complete": True}


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


if __name__ == "__main__":
    _main()
