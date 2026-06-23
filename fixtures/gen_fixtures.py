"""Generate fixture files for ChatGPT upload testing.

Each fixture embeds a unique sentinel string so we can verify ChatGPT actually
read the *content* (not just the filename).
"""
import csv
import io
import os
import struct
import zlib
from pathlib import Path

FX = Path(__file__).resolve().parent.parent / "fixtures"
FX.mkdir(parents=True, exist_ok=True)


def _w(name: str, data: bytes) -> Path:
    p = FX / name
    p.write_bytes(data)
    return p


# 1. PNG image (minimal valid 64x64 red PNG)
def _png() -> bytes:
    sig = b"\x89PNG\r\n\x1a\n"

    def chunk(t: bytes, d: bytes) -> bytes:
        return (struct.pack(">I", len(d)) + t + d +
                struct.pack(">I", zlib.crc32(t + d) & 0xffffffff))

    ihdr = struct.pack(">IIBBBBB", 64, 64, 8, 2, 0, 0, 0)  # 64x64, 8-bit RGB
    raw = b""
    for _ in range(64):
        raw += b"\x00" + b"\xff\x00\x00" * 64   # filter byte + red row
    idat = zlib.compress(raw)
    iend = b""
    return sig + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", iend)


# 2. JPEG (minimal valid, with sentinel in comment)
def _jpeg() -> bytes:
    soi = b"\xff\xd8"
    # APP0 marker
    app0 = b"\xff\xe0" + struct.pack(">H", 16) + b"JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    # COM marker with sentinel
    sentinel = b"FIXTURE_SENTINEL_IMG_ZX9"
    com = b"\xff\xfe" + struct.pack(">H", len(sentinel) + 2) + sentinel
    # minimal SOF0 (8x8, 1 component)
    sof = (b"\xff\xc0" + struct.pack(">H", 11) + b"\x08" +
           struct.pack(">HH", 8, 8) + b"\x01\x01\x11\x00")
    # DHT (minimal Huffman)
    dht = (b"\xff\xc4" + struct.pack(">H", 31) + b"\x00" +
           bytes([0,1,5,1,1,1,1,1,1,0,0,0,0,0,0,0]) +
           bytes(range(12)) + bytes(range(12, 20)))
    sos = b"\xff\xda" + struct.pack(">H", 8) + b"\x01\x01\x00\x00\x3f\x00"
    eoi = b"\xff\xd9"
    return soi + app0 + com + sof + dht + sos + b"\x00" * 8 + eoi


# 3. PDF with sentinel text
def _pdf() -> bytes:
    s = b"FIXTURE_SENTINEL_PDF_QW7"
    stream = (b"BT /F1 24 Tf 72 720 Td (ChatGPT Pro PDF fixture.) Tj ET\n"
              b"BT /F1 24 Tf 72 680 Td (" + s + b") Tj ET")
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = b"%PDF-1.4\n"
    offs = []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref_off = len(out)
    out += b"xref\n0 " + str(len(objs) + 1).encode() + b"\n"
    out += b"0000000000 65535 f \n"
    for off in offs:
        out += f"{off:010d} 00000 n \n".encode()
    out += (b"trailer\n<< /Size " + str(len(objs) + 1).encode() +
            b" /Root 1 0 R >>\nstartxref\n" + str(xref_off).encode() + b"\n%%EOF")
    return out


# 4. CSV with sentinel (single sentinel row for deterministic test)
def _csv() -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "name", "value"])
    for i in range(20):
        # only ONE row carries the unique sentinel so the test expectation is unambiguous
        val = "FIXTURE_SENTINEL_CSV_19" if i == 19 else f"row_value_{i}"
        w.writerow([i, f"row_{i}", val])
    return buf.getvalue().encode()


# 5. Plain text
def _txt() -> bytes:
    return (b"ChatGPT Pro TXT fixture.\n"
            b"FIXTURE_SENTINEL_TXT_M3K\n"
            b"Count to five in the reply to prove you read this.\n")


# 6. JSON
def _json() -> bytes:
    return (b'{\n  "fixture": "chatgpt-pro-test",\n'
            b'  "sentinel": "FIXTURE_SENTINEL_JSON_L8R",\n'
            b'  "numbers": [3, 1, 4, 1, 5, 9, 2, 6],\n'
            b'  "nested": {"deep": true, "count": 7}\n}\n')


# 7. Python source
def _py() -> bytes:
    return (b"# ChatGPT Pro PY fixture\n"
            b"SENTINEL = 'FIXTURE_SENTINEL_PY_V2X'\n"
            b"def add(a, b):\n    return a + b\n"
            b"# What does SENTINEL equal? And what does add(40,2) return?\n")


# 8. Markdown
def _md() -> bytes:
    return (b"# ChatGPT Pro MD Fixture\n\n"
            b"Sentinel: **FIXTURE_SENTINEL_MD_9P**\n\n"
            b"- item one\n- item two\n\n"
            b"Repeat the sentinel back.\n")


# 9. DOCX (minimal valid OOXML zip)
def _docx() -> bytes:
    import zipfile
    doc_xml = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
               b'<w:body>'
               b'<w:p><w:r><w:t>ChatGPT Pro DOCX fixture. Sentinel: FIXTURE_SENTINEL_DOCX_T5</w:t></w:r></w:p>'
               b'<w:p><w:r><w:t>Reply with the sentinel string to confirm read.</w:t></w:r></w:p>'
               b'</w:body></w:document>')
    ct = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          b'<Default Extension="xml" ContentType="application/xml"/>'
          b'<Override PartName="/word/document.xml" '
          b'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
          b'</Types>')
    rels = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            b'</Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels)
        z.writestr("word/document.xml", doc_xml)
    return buf.getvalue()


# 10. XLSX (minimal valid OOXML)
def _xlsx() -> bytes:
    import zipfile
    workbook = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                b'<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                b'<sheets><sheet name="S1" sheetId="1" r:id="rId1"/></sheets></workbook>')
    sheet = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             b'<sheetData>'
             b'<row r="1"><c r="A1" t="inlineStr"><is><t>Sentinel</t></is></c>'
             b'<c r="B1" t="inlineStr"><is><t>FIXTURE_SENTINEL_XLSX_4G</t></is></c></row>'
             b'<row r="2"><c r="A1" t="inlineStr"><is><t>Value</t></is></c>'
             b'<c r="B1" t="inlineStr"><is><t>42</t></is></c></row>'
             b'</sheetData></worksheet>')
    ct = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          b'<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          b'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          b'<Default Extension="xml" ContentType="application/xml"/>'
          b'<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          b'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
          b'</Types>')
    rels_root = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
                 b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
                 b'</Relationships>')
    rels_wb = (b'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
               b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
               b'<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
               b'</Relationships>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", ct)
        z.writestr("_rels/.rels", rels_root)
        z.writestr("xl/workbook.xml", workbook)
        z.writestr("xl/_rels/workbook.xml.rels", rels_wb)
        z.writestr("xl/worksheets/sheet1.xml", sheet)
    return buf.getvalue()


# 11. Large text (~60 KB) for long-input testing
def _big_txt() -> bytes:
    parts = [b"# Big-input fixture\n"]
    for i in range(1500):
        parts.append(f"Line {i:04d}: the quick brown fox jumps over the lazy dog. "
                     f"Token marker BIG_SENTINEL_{i:04d}.\n".encode())
    # hide a special needle deep in the middle
    parts[750] = ("NEEDLE_IN_HAYSTACK_UNIQ_7Q3Z9 -- if you can find and quote this "
                  "exact string, you truly processed the whole file.\n").encode()
    return b"".join(parts)


FIXTURES = {
    "img.png":      (_png,      "FIXTURE_SENTINEL_IMG_ZX9",      "PNG image"),
    "img.jpg":      (_jpeg,     "FIXTURE_SENTINEL_IMG_ZX9",      "JPEG image"),
    "doc.pdf":      (_pdf,      "FIXTURE_SENTINEL_PDF_QW7",      "PDF document"),
    "data.csv":     (_csv,      "FIXTURE_SENTINEL_CSV_19",       "CSV table"),
    "note.txt":     (_txt,      "FIXTURE_SENTINEL_TXT_M3K",      "Plain text"),
    "data.json":    (_json,     "FIXTURE_SENTINEL_JSON_L8R",     "JSON"),
    "code.py":      (_py,       "FIXTURE_SENTINEL_PY_V2X",       "Python source"),
    "readme.md":    (_md,       "FIXTURE_SENTINEL_MD_9P",        "Markdown"),
    "doc.docx":     (_docx,     "FIXTURE_SENTINEL_DOCX_T5",      "Word DOCX"),
    "sheet.xlsx":   (_xlsx,     "FIXTURE_SENTINEL_XLSX_4G",      "Excel XLSX"),
    "big.txt":      (_big_txt,  "NEEDLE_IN_HAYSTACK_UNIQ_7Q3Z9", "60KB long-input"),
}


def make_all() -> dict:
    out = {}
    for name, (fn, sentinel, desc) in FIXTURES.items():
        p = _w(name, fn())
        out[name] = {"path": str(p), "sentinel": sentinel, "desc": desc,
                     "size": p.stat().st_size}
    return out


if __name__ == "__main__":
    import json
    m = make_all()
    print(json.dumps(m, indent=2, ensure_ascii=False))
    print(f"\nGenerated {len(m)} fixtures in {FX}")
