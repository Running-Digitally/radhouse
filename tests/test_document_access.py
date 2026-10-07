"""Whole-original access, meaningful source locators and scope enforcement."""
import base64
import hashlib
from io import BytesIO
import json
from pathlib import Path
import subprocess
from uuid import uuid4
from zipfile import ZipFile, ZIP_DEFLATED

import pytest
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from radhouse.chat.attachments import Attachment, classify, MAX_TEXT
from radhouse.chat.document_access import DocumentAccess, MAX_RESULT_BYTES
from radhouse.chat import document_parser
from radhouse.domain.tasks import Rejected

CURSOR_KEY = b"test-server-scoped-secret-not-upload-content"  # Supplied by the future persisted grant.

def access(tmp_path, sources):
    files, calls = {}, []
    for name, data in sources:
        file_id = str(uuid4())
        path = tmp_path / file_id
        path.write_bytes(data)
        media, kind = classify(name, data[:4096])
        files[file_id] = Attachment(name, media, kind, path, file_id=file_id,
                                   stored_sha256=hashlib.sha256(data).hexdigest(), stored_size=len(data))

    def resolve(owner, file_id):
        calls.append((owner, file_id))
        if owner != "alice":
            raise Rejected("attachment_not_found", 404)
        return files[file_id]

    return DocumentAccess(resolve, owner="alice", file_ids=frozenset(files), cursor_key=CURSOR_KEY), files, calls


def pdf_pages(pages, *, encrypted=False):
    writer = PdfWriter()
    font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
    font_id = writer._add_object(font)
    for text in pages:
        page = writer.add_blank_page(400, 400)
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
            DictionaryObject({NameObject("/F1"): font_id})})
        if text:
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 40 340 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("private-fixture")
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def archive_files(files):
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return output.getvalue()


def test_pdf_fact_on_page121_is_searchable_and_selectively_readable(tmp_path):
    original = pdf_pages([f"Ordinary page {number}" for number in range(1, 121)] + ["Final allocation is 7349"])
    reader, files, _ = access(tmp_path, [("long-report.pdf", original)])
    file_id = next(iter(files))
    result = reader.search(file_id, "allocation")
    assert result.complete and not result.error and result.next_cursor is None
    assert len(result.passages) == 1
    assert result.passages[0].locator == "pdf:page:121:offset:0"
    assert "7349" in result.passages[0].text
    read = reader.read(file_id, "pdf:page:121")
    assert read.complete and read.passages[0].text == "Final allocation is 7349"
    assert files[file_id].data.read_bytes() == original


def parser_read(locator, *, position=0):
    return {"operation": "read", "locator": locator, "query": None,
            "position": position, "resume": None, "extension": ".pdf"}


@pytest.mark.parametrize("failing_neighbor", [1, 3, None])
def test_selected_pdf_extracts_only_requested_page_even_if_neighbor_fails(monkeypatch, failing_neighbor):
    import pypdf
    extractions = []
    class Page:
        def __init__(self, number): self.number = number
        def extract_text(self):
            extractions.append(self.number)
            if self.number == failing_neighbor:
                raise ValueError("private neighbor parsing failure")
            return f"Page {self.number} contents"
    class Reader:
        is_encrypted = False
        pages = [Page(1), Page(2), Page(3)]
    monkeypatch.setattr(pypdf, "PdfReader", lambda *a, **kw: Reader())
    result = document_parser._operate(b"synthetic pdf source", parser_read("pdf:page:2"))
    assert extractions == [2]
    assert result["complete"] and result["passages"][0]["text"] == "Page 2 contents"


@pytest.mark.parametrize("failing_neighbor", [1, 3, None])
def test_selected_slide_reads_only_requested_xml_even_if_neighbor_malformed(monkeypatch, failing_neighbor):
    files = {
        "ppt/presentation.xml": '<p:presentation xmlns:p="urn:slide" xmlns:r="urn:relationships"><p:sldIdLst><p:sldId r:id="r1"/><p:sldId r:id="r2"/><p:sldId r:id="r3"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": '<Relationships>' + ''.join(
            f'<Relationship Id="r{number}" Type="urn:relationships/slide" Target="slides/slide{number}.xml"/>'
            for number in range(1, 4)) + '</Relationships>',
    }
    for number in range(1, 4):
        files[f"ppt/slides/slide{number}.xml"] = ('malformed XML' if number == failing_neighbor else
            f'<a:slide xmlns:a="urn:drawing"><a:t>Slide {number} contents</a:t></a:slide>')
    reads = []
    original_xml = document_parser._xml
    def counted_xml(archive, path):
        if path.startswith("ppt/slides/"):
            reads.append(path)
        return original_xml(archive, path)
    monkeypatch.setattr(document_parser, "_xml", counted_xml)
    request = {**parser_read("slide:2"), "extension": ".pptx"}
    result = document_parser._operate(archive_files(files), request)
    assert reads == ["ppt/slides/slide2.xml"]
    assert result["complete"] and result["passages"][0]["text"] == "Slide 2 contents"


def test_large_text_past_existing_excerpt_and_compare_files(tmp_path):
    large = ("ordinary line\n" * 12000 + "Final budget: £8731\n").encode()
    assert len(large) > MAX_TEXT
    reader, files, _ = access(tmp_path, [("first.txt", large), ("second.txt", "Final budget: £9120\n".encode())])
    results = {attachment.name: reader.search(file_id, "final budget") for file_id, attachment in files.items()}
    assert "£8731" in results["first.txt"].passages[0].text
    assert results["first.txt"].passages[0].locator == "text:line:12001:offset:0"
    assert "£9120" in results["second.txt"].passages[0].text
    assert all(result.complete and result.error is None for result in results.values())
    assert len({result.file_id for result in results.values()}) == 2


def test_search_budget_requires_continuation_before_absence_can_be_concluded(tmp_path):
    body = ("nothing\n" * (document_parser.MAX_SCAN_UNITS + 7) + "Found distant answer\n").encode()
    reader, files, _ = access(tmp_path, [("distant.txt", body)])
    file_id = next(iter(files))
    first = reader.search(file_id, "distant answer")
    assert not first.complete and first.next_cursor and not first.passages and not first.error
    final = reader.search(file_id, "distant answer", first.next_cursor)
    assert final.complete and "distant answer" in final.passages[0].text
    checkpoint = json.loads(base64.urlsafe_b64decode(first.next_cursor))["body"]["resume"]
    assert checkpoint["cookie"] > 0 and checkpoint["index"] == document_parser.MAX_SCAN_UNITS - 1


def test_text_checkpoint_survives_new_access_instance_and_utf8_bom_crlf(tmp_path):
    text = ("αβ😀\r\n" * 12 + "the distant end\r\n")
    reader, files, _ = access(tmp_path, [("unicode-lines.txt", b"\xef\xbb\xbf" + text.encode())])
    file_id = next(iter(files))
    first = reader.read(file_id)
    assert first.next_cursor
    fresh = DocumentAccess(reader._resolve, owner="alice", file_ids=frozenset(files), cursor_key=CURSOR_KEY)
    second = fresh.read(file_id, cursor=first.next_cursor)
    assert second.complete and not second.error
    assert "".join(p.text for p in first.passages + second.passages) == text.replace("\r\n", "\n")


def test_unicode_query_matches_across_reader_chunk_boundary(tmp_path):
    body = ("α" * (document_parser.CHUNK_CHARS - 3) + "Straße😀 end").encode()
    reader, files, _ = access(tmp_path, [("unicode.txt", body)])
    result = reader.search(next(iter(files)), "STRASSE😀")
    assert result.complete and len(result.passages) == 1 and "Straße😀" in result.passages[0].text
    locator = result.passages[0].locator
    read = reader.read(next(iter(files)), locator)
    assert "Straße😀" in "".join(p.text for p in read.passages)


def test_casefold_expansion_uses_enough_overlap_for_long_boundary_match(tmp_path):
    needle = "ß" * 512
    matching_text = "ss" * 512
    body = "x" * (document_parser.CHUNK_CHARS - 600) + matching_text + " tail"
    reader, files, _ = access(tmp_path, [("expanded.txt", body.encode())])
    result = reader.search(next(iter(files)), needle)
    assert result.complete and len(result.passages) == 1
    assert matching_text in result.passages[0].text


def test_search_does_not_lose_new_hit_when_prior_chunk_overlap_also_matches(tmp_path):
    first = "x" * (document_parser.CHUNK_CHARS - 20) + "answer old" + "x" * 10
    reader, files, _ = access(tmp_path, [("repeated.txt", (first + "new answer").encode())])
    result = reader.search(next(iter(files)), "answer")
    assert result.complete and len(result.passages) == 2
    assert "new answer" in result.passages[-1].text


def test_long_single_line_reads_are_bounded_and_continuations_preserve_all_text(tmp_path):
    text = "😀β" * 19000
    reader, files, _ = access(tmp_path, [("large-line.txt", text.encode())])
    file_id = next(iter(files))
    parts, cursor = [], None
    for _ in range(50):
        result = reader.read(file_id, cursor=cursor)
        assert not result.error and len(result.passages) <= 8
        assert len(json.dumps(result.__dict__, default=lambda p: p.__dict__, ensure_ascii=False).encode()) < MAX_RESULT_BYTES
        parts.extend(p.text for p in result.passages)
        if result.complete:
            break
        assert result.next_cursor
        cursor = result.next_cursor
    else:
        pytest.fail("reader failed to finish")
    assert "".join(parts) == text


def test_json_escaping_counts_toward_output_budget_instead_of_failing_valid_text(tmp_path):
    text = "\t\\\"" * 11000
    reader, files, _ = access(tmp_path, [("escaped.txt", text.encode())])
    file_id = next(iter(files))
    pieces, cursor = [], None
    for _ in range(50):
        result = reader.read(file_id, cursor=cursor)
        assert not result.error
        assert len(json.dumps(result.__dict__, default=lambda p: p.__dict__, ensure_ascii=False).encode()) < MAX_RESULT_BYTES
        pieces.extend(p.text for p in result.passages)
        if result.complete:
            break
        cursor = result.next_cursor
    assert "".join(pieces) == text


def test_word_current_revisions_paragraph_refs_and_long_paragraph(tmp_path):
    original = archive_files({"word/document.xml": '<w:document xmlns:w="urn:word"><w:body>'
        '<w:p><w:r><w:t>Price: </w:t></w:r><w:del><w:r><w:delText>100</w:delText></w:r></w:del>'
        '<w:ins><w:r><w:t>200</w:t></w:r></w:ins></w:p>'
        '<w:moveFrom><w:p><w:r><w:t>Obsolete moved text</w:t></w:r></w:p></w:moveFrom>'
        '<w:p><w:r><w:t>' + "x" * 9000 + ' final paragraph answer</w:t></w:r></w:p></w:body></w:document>'})
    reader, files, _ = access(tmp_path, [("revisions.docx", original)])
    file_id = next(iter(files))
    assert reader.read(file_id, "word:paragraph:1").passages[0].text == "Price: 200"
    found = reader.search(file_id, "final paragraph answer")
    assert found.complete and found.passages[0].locator.startswith("word:paragraph:2:offset:")
    assert not reader.search(file_id, "Obsolete").passages


def test_workbook_named_unicode_sheet_cells_and_cached_formula(tmp_path):
    original = archive_files({
        "xl/workbook.xml": '<s:workbook xmlns:s="urn:sheet" xmlns:r="urn:relationships"><s:sheets><s:sheet name="Budget: α" r:id="r1"/></s:sheets></s:workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="r1" Type="urn:relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/sharedStrings.xml": '<s:sst xmlns:s="urn:sheet"><s:si><s:r><s:t>Annual </s:t></s:r><s:r><s:t>budget</s:t></s:r></s:si></s:sst>',
        "xl/worksheets/sheet1.xml": '<s:worksheet xmlns:s="urn:sheet"><s:sheetData><s:row><s:c r="A1" t="s"><s:v>0</s:v></s:c><s:c r="D42"><s:f>SUM(A1:A9)</s:f><s:v>7200</s:v></s:c></s:row></s:sheetData></s:worksheet>',
    })
    reader, files, _ = access(tmp_path, [("budget.xlsx", original)])
    file_id = next(iter(files))
    result = reader.search(file_id, "7200")
    passage = result.passages[0]
    assert passage.locator == "sheet:Budget%3A%20%CE%B1:cell:D42:offset:0"
    assert passage.label == "Budget: α!D42" and "cached value; formula: SUM(A1:A9)" in passage.text
    assert reader.read(file_id, passage.locator).passages[0] == passage
    assert reader.search(file_id, "Annual budget").passages[0].locator.endswith("cell:A1:offset:0")


def test_workbook_with_chart_sheet_still_reads_worksheet_cells(tmp_path):
    body = archive_files({
        "xl/workbook.xml": '<s:workbook xmlns:s="urn:sheet" xmlns:r="urn:relationships"><s:sheets><s:sheet name="Chart" r:id="chart"/><s:sheet name="Budget" r:id="table"/></s:sheets></s:workbook>',
        "xl/_rels/workbook.xml.rels": '<Relationships><Relationship Id="chart" Type="urn:relationships/chartsheet" Target="chartsheets/sheet1.xml"/><Relationship Id="table" Type="urn:relationships/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/chartsheets/sheet1.xml": 'Chart text is not a stored worksheet cell and is not parsed.',
        "xl/worksheets/sheet1.xml": '<s:worksheet xmlns:s="urn:sheet"><s:sheetData><s:row><s:c r="D42"><s:v>7200</s:v></s:c></s:row></s:sheetData></s:worksheet>',
    })
    reader, files, _ = access(tmp_path, [("with-chart.xlsx", body)])
    result = reader.search(next(iter(files)), "7200")
    assert result.complete and not result.error
    assert result.passages[0].locator == "sheet:Budget:cell:D42:offset:0"


@pytest.mark.parametrize("relationship_type,target", [("urn:relationships/unknown", "worksheets/sheet1.xml"),
    ("urn:relationships/worksheet", "../worksheets/sheet1.xml"),
    ("urn:relationships/worksheet", "worksheets/missing.xml")])
def test_unknown_or_broken_worksheet_relationships_still_fail(tmp_path, relationship_type, target):
    body = archive_files({
        "xl/workbook.xml": '<s:workbook xmlns:s="urn:sheet" xmlns:r="urn:relationships"><s:sheets><s:sheet name="Budget" r:id="table"/></s:sheets></s:workbook>',
        "xl/_rels/workbook.xml.rels": f'<Relationships><Relationship Id="table" Type="{relationship_type}" Target="{target}"/></Relationships>',
        "xl/worksheets/sheet1.xml": '<s:worksheet xmlns:s="urn:sheet"><s:sheetData><s:row><s:c r="D42"><s:v>7200</s:v></s:c></s:row></s:sheetData></s:worksheet>',
    })
    reader, files, _ = access(tmp_path, [("broken.xlsx", body)])
    result = reader.search(next(iter(files)), "7200")
    assert result.error == "document_unreadable" and not result.complete


def test_slide_locators_follow_presentation_order_not_zip_filename_order(tmp_path):
    original = archive_files({
        "ppt/presentation.xml": '<p:presentation xmlns:p="urn:slide" xmlns:r="urn:relationships"><p:sldIdLst><p:sldId r:id="second"/><p:sldId r:id="first"/></p:sldIdLst></p:presentation>',
        "ppt/_rels/presentation.xml.rels": '<Relationships><Relationship Id="first" Type="urn:relationships/slide" Target="slides/slide1.xml"/><Relationship Id="second" Type="urn:relationships/slide" Target="/ppt/slides/slide2.xml"/></Relationships>',
        "ppt/slides/slide1.xml": '<a:slide xmlns:a="urn:drawing"><a:t>Closing result</a:t></a:slide>',
        "ppt/slides/slide2.xml": '<a:slide xmlns:a="urn:drawing"><a:t>Opening context</a:t></a:slide>',
        "ppt/slides/slide3.xml": '<a:slide xmlns:a="urn:drawing"><a:t>Orphan</a:t></a:slide>',
    })
    reader, files, _ = access(tmp_path, [("ordered.pptx", original)])
    file_id = next(iter(files))
    assert reader.search(file_id, "Opening").passages[0].locator == "slide:1:offset:0"
    assert reader.read(file_id, "slide:2").passages[0].text == "Closing result"
    assert reader.search(file_id, "Orphan").complete and not reader.search(file_id, "Orphan").passages


def test_unattached_or_other_owner_file_denied_before_parser_or_resolver(tmp_path, monkeypatch):
    reader, files, calls = access(tmp_path, [("mine.txt", b"private")])
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("parser called"))
    with pytest.raises(Rejected, match="attachment_not_found"):
        reader.read(str(uuid4()))
    assert not calls
    wrong_owner = DocumentAccess(reader._resolve, owner="bob", file_ids=frozenset(files), cursor_key=CURSOR_KEY)
    with pytest.raises(Rejected, match="attachment_not_found"):
        wrong_owner.search(next(iter(files)), "private")


@pytest.mark.parametrize("change", ["query", "operation", "file", "sha256", "malformed"])
def test_continuations_are_bound_to_source_and_operation(tmp_path, change):
    reader, files, _ = access(tmp_path, [("one.txt", b"answer\n" * 12), ("two.txt", b"answer\n" * 12)])
    first, second = tuple(files)
    cursor = reader.search(first, "answer").next_cursor
    assert cursor
    with pytest.raises(Rejected, match="document_cursor_invalid"):
        if change == "query": reader.search(first, "different", cursor)
        elif change == "operation": reader.read(first, cursor=cursor)
        elif change == "file": reader.search(second, "answer", cursor)
        elif change == "sha256":
            value = json.loads(base64.urlsafe_b64decode(cursor))
            value["body"]["binding"]["sha256"] = "0" * 64
            reader.search(first, "answer", base64.urlsafe_b64encode(json.dumps(value).encode()).decode())
        else: reader.search(first, "answer", "invalid!")


def test_cursor_authentication_rejects_fabricated_source_locators_before_parser(tmp_path, monkeypatch):
    reader, files, _ = access(tmp_path, [("source.txt", b"actual text\n" * 12)])
    file_id = next(iter(files))
    cursor = reader.read(file_id).next_cursor
    signed = json.loads(base64.urlsafe_b64decode(cursor))
    signed["body"]["position"] = 0
    signed["body"]["resume"] = {"cookie": 0, "line": 900, "offset": 500, "index": 0, "has_text": True}
    forged = base64.urlsafe_b64encode(json.dumps(signed).encode()).decode()
    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: pytest.fail("tampered cursor reached parser"))
    with pytest.raises(Rejected, match="document_cursor_invalid"):
        reader.read(file_id, cursor=forged)
    unsigned = base64.urlsafe_b64encode(json.dumps(signed["body"]).encode()).decode()
    with pytest.raises(Rejected, match="document_cursor_invalid"):
        reader.read(file_id, cursor=unsigned)


def test_cursor_key_is_required_and_scoped_across_fresh_instances(tmp_path):
    reader, files, _ = access(tmp_path, [("source.txt", b"actual text\n" * 12)])
    file_id = next(iter(files))
    cursor = reader.read(file_id).next_cursor
    wrong_scope = DocumentAccess(reader._resolve, owner="alice", file_ids=frozenset(files), cursor_key=b"z" * 32)
    with pytest.raises(Rejected, match="document_cursor_invalid"):
        wrong_scope.read(file_id, cursor=cursor)
    with pytest.raises(ValueError, match="invalid_document_scope"):
        DocumentAccess(reader._resolve, owner="alice", file_ids=frozenset(files), cursor_key=b"z" * 31)
    with pytest.raises(TypeError):
        DocumentAccess(reader._resolve, owner="alice", file_ids=frozenset(files))


def test_selected_pdf_continuation_only_reextracts_target_page(monkeypatch):
    import pypdf
    text = "selected page content " * 2400
    extractions = []
    class Page:
        def __init__(self, number): self.number = number
        def extract_text(self):
            extractions.append(self.number)
            if self.number != 2:
                raise ValueError("neighbor must not be extracted")
            return text
    class Reader:
        is_encrypted = False
        pages = [Page(1), Page(2), Page(3)]
    monkeypatch.setattr(pypdf, "PdfReader", lambda *a, **kw: Reader())
    pieces, position = [], 0
    for _ in range(10):
        result = document_parser._operate(b"synthetic pdf source", parser_read("pdf:page:2", position=position))
        pieces.extend(p["text"] for p in result["passages"])
        assert all(p["locator"].startswith("pdf:page:2:") for p in result["passages"])
        if result["complete"]:
            break
        position = result["next_position"]
    assert "".join(pieces) == text and all(number == 2 for number in extractions)


@pytest.mark.parametrize("body,error", [(pdf_pages(["secret"], encrypted=True), "document_encrypted"),
                                         (pdf_pages([""]), "document_needs_ocr")])
def test_reader_failure_is_honest_and_keeps_original(tmp_path, body, error):
    reader, files, _ = access(tmp_path, [("unreadable.pdf", body)])
    file_id = next(iter(files))
    result = reader.search(file_id, "secret")
    assert result.error == error and not result.complete and not result.passages
    assert files[file_id].data.read_bytes() == body


@pytest.mark.parametrize("xml", ['<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x>&secret;</x>',
    '<!DOCTYPE x [<!ENTITY secret "expanded">]><x>&secret;</x>'])
def test_office_entities_cannot_read_files_or_expand(tmp_path, xml):
    body = archive_files({"word/document.xml": xml})
    reader, files, _ = access(tmp_path, [("entity.docx", body)])
    result = reader.read(next(iter(files)))
    assert result.error == "document_unreadable" and not result.passages


def test_subprocess_timeout_errors_are_redacted_and_release_slot(tmp_path, monkeypatch):
    reader, files, _ = access(tmp_path, [("report.txt", b"normal text")])
    file_id = next(iter(files))
    real = subprocess.run
    def timeout(*args, **kw):
        raise subprocess.TimeoutExpired("private path or text", 15)
    monkeypatch.setattr(subprocess, "run", timeout)
    result = reader.read(file_id)
    assert result.error == "document_operation_exhausted" and "private" not in str(result)
    monkeypatch.setattr(subprocess, "run", real)
    assert reader.read(file_id).passages[0].text == "normal text"


def test_catalog_contains_immutable_metadata_and_no_paths(tmp_path):
    reader, files, _ = access(tmp_path, [("report.txt", b"text")])
    metadata = reader.catalog()[0]
    assert metadata["file_id"] in files and metadata["sha256"] == hashlib.sha256(b"text").hexdigest()
    assert metadata["locator_kind"] == "line"
    assert str(tmp_path) not in json.dumps(metadata)


def test_selected_blank_pdf_page_needs_ocr_and_offsets_outside_source_fail(tmp_path):
    reader, files, _ = access(tmp_path, [("mixed.pdf", pdf_pages(["", "Readable text"]))])
    file_id = next(iter(files))
    assert reader.read(file_id, "pdf:page:1").error == "document_needs_ocr"
    assert reader.read(file_id, "pdf:page:2:offset:999999").error == "document_locator_not_found"
    assert reader.read(file_id, "pdf:page:99").error == "document_locator_not_found"


def test_blank_tail_after_search_continuation_is_a_complete_zero_match(tmp_path):
    body = ("answer\n" * 8 + "\n\n").encode()
    reader, files, _ = access(tmp_path, [("trailing.txt", body)])
    file_id = next(iter(files))
    first = reader.search(file_id, "answer")
    assert not first.complete and first.next_cursor
    final = reader.search(file_id, "answer", first.next_cursor)
    assert final.complete and not final.error and not final.passages


def test_one_active_parser_child_and_busy_response_has_no_standing_queue(tmp_path):
    from radhouse.chat.document_access import _PARSER_SLOT
    reader, files, _ = access(tmp_path, [("report.txt", b"content")])
    assert _PARSER_SLOT.acquire(blocking=False)
    try:
        result = reader.read(next(iter(files)))
        assert result.error == "document_reader_busy" and not result.complete
    finally:
        _PARSER_SLOT.release()


def test_document_catalog_reports_unsupported_content(tmp_path):
    reader, _, _ = access(tmp_path, [("report.pdf", pdf_pages(["text"]))])
    assert "scanned text require OCR" in reader.catalog()[0]["reader_scope"]
