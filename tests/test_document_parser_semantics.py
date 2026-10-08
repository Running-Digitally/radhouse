"""Parser contracts measured directly while child-process budget tests stay intact."""
import base64
import hashlib

import pytest

from radhouse.chat import document_parser as parser
from tests.test_document_access import archive_files, pdf_pages


def read(data, extension, **changes):
    request = {"operation": "read", "query": None, "locator": None, "position": 0, "resume": None,
               "extension": extension, "data": base64.b64encode(data).decode(),
               "sha256": hashlib.sha256(data).hexdigest(), **changes}
    return parser._verified_operate(request)


@pytest.mark.parametrize("extension,data,locator,text", [
    (".txt", b"First line\nSecond line\n", "text:line:2:offset:0", "Second line\n"),
    (".pdf", pdf_pages(["First page", "Second page"]), "pdf:page:2:offset:0", "Second page"),
    (".docx", archive_files({"word/document.xml":
        '<w:document xmlns:w="urn:word"><w:body><w:moveFrom><w:p><w:r><w:t>Old</w:t></w:r></w:p></w:moveFrom>'
        '<w:p><w:r><w:t>Current</w:t><w:tab/><w:t>text</w:t><w:br/></w:r><w:del><w:r><w:t>Deleted</w:t></w:r></w:del>'
        '</w:p></w:body></w:document>'}), "word:paragraph:1:offset:0", "Current\ttext\n"),
    (".xlsx", archive_files({
        "xl/workbook.xml": '<s:workbook xmlns:s="urn:sheet" xmlns:r="urn:relationships"><s:sheets><s:sheet name="Budget" r:id="table"/></s:sheets></s:workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="table" Type="urn:relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": '<s:sst xmlns:s="urn:sheet"><s:si><s:r><s:t>Annual </s:t></s:r><s:r><s:t>budget</s:t></s:r></s:si></s:sst>',
        "xl/worksheets/sheet1.xml": '<s:worksheet xmlns:s="urn:sheet"><s:sheetData><s:row><s:c r="A1" t="s"><s:v>0</s:v></s:c><s:c r="A2" t="inlineStr"><s:is><s:t>Next year</s:t></s:is></s:c></s:row></s:sheetData></s:worksheet>',
    }), "sheet:Budget:cell:A1:offset:0", "Annual budget"),
    (".pptx", archive_files({
        "ppt/presentation.xml": '<p:presentation xmlns:p="urn:slide" xmlns:r="urn:relationships"><p:sldIdLst><p:sldId r:id="second"/><p:sldId r:id="first"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="first" Type="urn:relationships/slide" Target="slides/slide1.xml"/><Relationship Id="second" Type="urn:relationships/slide" Target="/ppt/slides/slide2.xml"/></Relationships>',
        "ppt/slides/slide1.xml": '<a:slide xmlns:a="urn:drawing"><a:t>Closing result</a:t></a:slide>',
        "ppt/slides/slide2.xml": '<a:slide xmlns:a="urn:drawing"><a:t>Opening context</a:t></a:slide>',
    }), "slide:1:offset:0", "Opening context"),
])
def test_verified_formats_preserve_selected_source_locators(extension, data, locator, text):
    result = read(data, extension, locator=locator)
    assert result["complete"]
    assert len(result["passages"]) == 1
    assert result["passages"][0]["locator"] == locator
    assert result["passages"][0]["text"] == text


def test_direct_text_continuations_preserve_unicode_and_every_line():
    text = "αβ😀\r\n" * 20
    data = b"\xef\xbb\xbf" + text.encode()
    result = read(data, ".txt")
    parts = [passage["text"] for passage in result["passages"]]
    for _ in range(4):
        if result["complete"]:
            break
        result = read(data, ".txt", position=result["next_position"], resume=result["next_resume"])
        parts.extend(passage["text"] for passage in result["passages"])
    assert result["complete"]
    assert "".join(parts) == text.replace("\r\n", "\n")


def test_direct_search_preserves_casefolded_match_across_chunk_boundary():
    data = ("α" * (parser.CHUNK_CHARS - 3) + "Straße😀 end").encode()
    result = read(data, ".txt", operation="search", query="STRASSE😀")
    assert result["complete"]
    assert len(result["passages"]) == 1
    assert "Straße😀" in result["passages"][0]["text"]


@pytest.mark.parametrize("locator", ["text:line:0", "text:line:01", "text:line:2", "text:line:1:offset:99", "text:line:١"])
def test_direct_locator_validation_cannot_invent_passages(locator):
    with pytest.raises(ValueError, match="document_locator_not_found"):
        read(b"One line", ".txt", locator=locator)


def test_direct_verification_rejects_source_hash_mismatch():
    with pytest.raises(ValueError, match="document_source_changed"):
        read(b"Original", ".txt", sha256=hashlib.sha256(b"Replaced").hexdigest())


@pytest.mark.parametrize("xml", [
    '<!DOCTYPE document [<!ENTITY secret SYSTEM "file:///etc/passwd">]><document>&secret;</document>',
    '<!DOCTYPE document [<!ENTITY expanded "unsafe">]><document>&expanded;</document>',
])
def test_direct_office_parser_rejects_external_and_expanding_entities(xml):
    with pytest.raises(ValueError, match="document_unreadable"):
        read(archive_files({"word/document.xml": xml}), ".docx")


def test_direct_pdf_distinguishes_encryption_from_blank_page():
    with pytest.raises(ValueError, match="document_encrypted"):
        read(pdf_pages(["Secret"], encrypted=True), ".pdf")
    with pytest.raises(ValueError, match="document_needs_ocr"):
        read(pdf_pages([""]), ".pdf", locator="pdf:page:1")
