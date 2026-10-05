"""Text-only PDF/OOXML extraction in a bounded disposable child process."""
import base64
from io import BytesIO
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


def _extract(data, extension):
    if extension == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(data), strict=True)
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
    else:
        with ZipFile(BytesIO(data)) as archive:
            entries = archive.infolist()
            if (len(entries) > 2000 or sum(e.file_size for e in entries) > 32 * 1024 * 1024
                    or any(e.flag_bits & 1 or e.file_size / max(e.compress_size, 1) > 200 for e in entries)):
                raise ValueError("document_too_complex")
            names = archive.namelist()
            if len(set(names)) != len(names) or any("vbaproject" in n.lower() for n in names):
                raise ValueError("document_unreadable")
            if extension == ".docx":
                xml = _xml(archive, "word/document.xml")
                text = "\n".join("".join(n.itertext()) for n in xml.iter() if n.tag.endswith("}p"))
            elif extension == ".pptx":
                import re
                slides = sorted((n for n in names if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)), key=lambda n:int(re.search(r"(\d+)\.xml", n)[1]))
                text = "\n\n".join(f"Slide {i+1}\n" + "\n".join(n.text or "" for n in _xml(archive, name).iter() if n.tag.endswith("}t")) for i,name in enumerate(slides))
            else:
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
                    rows = []
                    for row in _xml(archive, target).iter():
                        if not row.tag.endswith("}row"): continue
                        values = []
                        for cell in row:
                            value = next((n.text or "" for n in cell if n.tag.endswith("}v")), "")
                            if cell.attrib.get("t") == "s": value = strings[int(value)]
                            if cell.attrib.get("t") == "inlineStr": value = "".join(n.text or "" for n in cell.iter() if n.tag.endswith("}t"))
                            formula = next((n.text for n in cell if n.tag.endswith("}f")), None)
                            # Never execute formulas or follow external links.
                            if formula: value = f"{value} [formula: {formula}]"
                            values.append(f"{cell.attrib.get('r','cell')}: {value}")
                        rows.append(" | ".join(values))
                    parts.append(sheet.attrib.get("name", "Sheet") + "\n" + "\n".join(rows))
                text = "\n\n".join(parts)
    if not text.strip(): raise ValueError("document_unreadable")
    if len(text.encode()) > MAX_TEXT: raise ValueError("attachment_text_too_large")
    return text


def extract_document(attachment):
    from pathlib import PurePath
    payload = json.dumps({"extension":PurePath(attachment.name).suffix.lower(),"data":base64.b64encode(attachment.data).decode()})
    try:
        result = subprocess.run([sys.executable, "-m", "radhouse.chat.documents"], input=payload,
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
        print(json.dumps({"text":_extract(base64.b64decode(value["data"],validate=True),value["extension"])},ensure_ascii=False))
    except Exception as exc:
        code = str(exc) if isinstance(exc,ValueError) and str(exc) in {"document_unreadable","document_encrypted","document_too_complex","document_needs_ocr","attachment_text_too_large"} else "document_unreadable"
        print(json.dumps({"error":code}))


if __name__ == "__main__":
    _main()
