"""Text-only PDF/OOXML extraction in a bounded disposable child process."""
import base64
from io import BytesIO
from pathlib import Path
import json
import os
import resource
import subprocess
import sys
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from radhouse.domain.tasks import Rejected
from .attachments import MAX_TEXT


def _xml(archive, name):
    data = archive.read(name)
    markup = data.replace(b"\x00",b"").upper()
    if b"<!DOCTYPE" in markup or b"<!ENTITY" in markup:
        raise ValueError("document_unreadable")
    return ET.fromstring(data)


def _local_name(node):
    return node.tag.rsplit("}", 1)[-1]


def _word_text(node):
    name = _local_name(node)
    if name in {"del", "moveFrom"}: return ""
    if name == "t": return node.text or ""
    if name == "tab": return "\t"
    if name in {"br", "cr"}: return "\n"
    return "".join(_word_text(child) for child in node)


def _word_paragraphs(node):
    if _local_name(node) in {"del", "moveFrom"}: return []
    if _local_name(node) == "p": return [_word_text(node)]
    return [text for child in node for text in _word_paragraphs(child)]


def _presentation_slides(archive):
    import re
    presentation = _xml(archive, "ppt/presentation.xml")
    relationships = _xml(archive, "ppt/_rels/presentation.xml.rels")
    targets = {}
    for relationship in relationships:
        identity = relationship.attrib["Id"]
        if identity in targets: raise ValueError("document_unreadable")
        targets[identity] = relationship.attrib
    slides = []
    for slide in presentation.iter():
        if _local_name(slide) != "sldId": continue
        identity = next((value for key,value in slide.attrib.items() if key.endswith("}id")), None)
        relationship = targets.get(identity, {})
        if relationship.get("TargetMode") == "External" or not relationship.get("Type", "").endswith("/slide"):
            raise ValueError("document_unreadable")
        target = relationship.get("Target", "")
        target = target.lstrip("/") if target.startswith("/ppt/") else "ppt/" + target
        if not re.fullmatch(r"ppt/slides/[^/\\?#]+\.xml", target) or ".." in target:
            raise ValueError("document_unreadable")
        slides.append(target)
    return slides


def _extract(data, extension):
    if extension == ".pdf":
        text = _pdf_text(data)
    else:
        with ZipFile(data if isinstance(data, Path) else BytesIO(data)) as archive:
            names = _checked_archive_names(archive)
            if extension == ".docx":
                xml = _xml(archive, "word/document.xml")
                text = "\n".join(_word_paragraphs(xml))
            elif extension == ".pptx":
                slides = _presentation_slides(archive)
                text = "\n\n".join(f"Slide {i+1}\n" + "\n".join(n.text or "" for n in _xml(archive, name).iter() if n.tag.endswith("}t")) for i,name in enumerate(slides))
            else:
                text = _spreadsheet_text(archive, names)
    if not text.strip(): raise ValueError("document_unreadable")
    # This is an automatic excerpt, not a condition for retaining an original.
    return text.encode()[:MAX_TEXT].decode("utf-8", errors="ignore")


def extract_document(attachment):
    from pathlib import PurePath
    payload = {"extension":PurePath(attachment.name).suffix.lower()}
    if isinstance(attachment.data, Path): payload["path"] = str(attachment.data)
    else: payload["data"] = base64.b64encode(attachment.data).decode()
    try:
        result = subprocess.run([sys.executable, "-m", "radhouse.chat.documents"], input=json.dumps(payload),
            text=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=15, env={**os.environ,"PYTHONDONTWRITEBYTECODE":"1"})
        if result.returncode or len(result.stdout.encode()) > MAX_TEXT * 6 + 32768:
            raise Rejected("document_too_complex", 422)
        value = json.loads(result.stdout)
        if "error" in value: raise Rejected(value["error"], 422)
        return value["text"]
    except (subprocess.TimeoutExpired, json.JSONDecodeError, KeyError, OSError):
        raise Rejected("document_unreadable", 422) from None


def _main():
    resource.setrlimit(resource.RLIMIT_CPU, (10,10))
    # A parser may expand a compressed PDF stream; bound its address space on
    # Linux. macOS does not reliably enforce RLIMIT_AS for Python processes.
    if sys.platform.startswith("linux"):
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024,512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (0,0))
    try:
        value = json.load(sys.stdin)
        data = Path(value["path"]) if "path" in value else base64.b64decode(value["data"],validate=True)
        print(json.dumps({"text":_extract(data,value["extension"])},ensure_ascii=False))
    except Exception as exc:
        code = str(exc) if isinstance(exc,ValueError) and str(exc) in {"document_unreadable","document_encrypted","document_too_complex","document_needs_ocr","attachment_text_too_large"} else "document_unreadable"
        print(json.dumps({"error":code}))


def _pdf_text(data):
    from pypdf import PdfReader
    reader = PdfReader(data if isinstance(data, Path) else BytesIO(data), strict=True)
    if reader.is_encrypted:
        raise ValueError("document_encrypted")
    if len(reader.pages) > 100:
        raise ValueError("document_too_complex")
    parts, has_text = [], False
    for i, page in enumerate(reader.pages):
        content = page.get_contents()
        if content is not None and len(content.get_data()) > 2 * 1024 * 1024:
            raise ValueError("document_too_complex")
        page_text = page.extract_text() or ""
        has_text = has_text or bool(page_text.strip())
        parts.append(f"Page {i + 1}\n" + page_text)
    text = "\n\n".join(parts)
    if not has_text:
        raise ValueError("document_needs_ocr")
    return text


def _checked_archive_names(archive):
    entries = archive.infolist()
    if (len(entries) > 2000 or sum(e.file_size for e in entries) > 32 * 1024 * 1024
            or any(e.flag_bits & 1 or e.file_size / max(e.compress_size, 1) > 200 for e in entries)):
        raise ValueError("document_too_complex")
    names = archive.namelist()
    if len(set(names)) != len(names) or any("vbaproject" in n.lower() for n in names):
        raise ValueError("document_unreadable")
    return names


def _spreadsheet_cell_value(cell, strings):
    value = next((n.text or "" for n in cell if n.tag.endswith("}v")), "")
    if cell.attrib.get("t") == "s": value = strings[int(value)]
    if cell.attrib.get("t") == "inlineStr": value = "".join(n.text or "" for n in cell.iter() if n.tag.endswith("}t"))
    formula = next((n.text for n in cell if n.tag.endswith("}f")), None)
    # Never execute formulas or follow external links.
    if formula: value = f"{value} [formula: {formula}]"
    return value


def _spreadsheet_rows(archive, target, strings):
    rows = []
    for row in _xml(archive, target).iter():
        if not row.tag.endswith("}row"): continue
        values = []
        for cell in row:
            value = _spreadsheet_cell_value(cell, strings)
            values.append(f"{cell.attrib.get('r','cell')}: {value}")
        rows.append(" | ".join(values))
    return rows


def _spreadsheet_text(archive, names):
    strings = []
    if "xl/sharedStrings.xml" in names:
        strings = ["".join(n.itertext()) for n in _xml(archive, "xl/sharedStrings.xml").iter() if n.tag.endswith("}si")]
    workbook = _xml(archive, "xl/workbook.xml")
    rels = _xml(archive, "xl/_rels/workbook.xml.rels")
    targets = {r.attrib["Id"]:r.attrib["Target"] for r in rels}
    parts = []
    for sheet in workbook.iter():
        if not sheet.tag.endswith("}sheet"): continue
        rid = sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
        target = targets.get(rid, "")
        target = target.lstrip("/") if target.startswith("/xl/") else "xl/" + target
        if not target.startswith("xl/worksheets/") or ".." in target:
            raise ValueError("document_unreadable")
        rows = _spreadsheet_rows(archive, target, strings)
        parts.append(sheet.attrib.get("name", "Sheet") + "\n" + "\n".join(rows))
    text = "\n\n".join(parts)
    return text


if __name__ == "__main__":
    _main()
