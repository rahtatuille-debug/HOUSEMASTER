"""
Uploads that would exhaust the server: Excel "zip bombs", sheets with millions of empty rows and
photos that claim enormous dimensions. Each must be refused quickly, before it's unpacked or decoded.
"""
import io
import time
import zipfile

import openpyxl
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import SimpleTestCase

from accounts.tests import SchoolScopedAPITestCase
from housemaster.uploads import MARK_SHEET_MAX_UNPACKED, UnsafeWorkbook, check_xlsx
from students.models import Student

NS = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
CONTENT_TYPES = (
    '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/worksheets/sheet1.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
    '<Override PartName="/xl/sharedStrings.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/></Types>')
RELS = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="xl/workbook.xml"/></Relationships>')
WORKBOOK_RELS = (
    '<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
    'Target="worksheets/sheet1.xml"/><Relationship Id="rId2" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
    'Target="sharedStrings.xml"/></Relationships>')


def raw_xlsx(sheet_name="Marks", header=("Admission no.", "Mark"), empty_rows=0, shared_text_mb=0):
    """A minimal .xlsx written by hand: a header row, then optional empty rows or padding text."""
    cells = "".join(f'<c r="{chr(65 + i)}1" t="inlineStr"><is><t>{h}</t></is></c>' for i, h in enumerate(header))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("xl/workbook.xml", f'<?xml version="1.0"?><workbook {NS} xmlns:r="http://schemas.openxmlformats.org/'
                   f'officeDocument/2006/relationships"><sheets><sheet name="{sheet_name}" sheetId="1" r:id="rId1"/>'
                   '</sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels", WORKBOOK_RELS)
        with z.open("xl/worksheets/sheet1.xml", "w") as f:
            f.write(f'<?xml version="1.0"?><worksheet {NS}><sheetData><row r="1">{cells}</row>'.encode())
            for start in range(2, empty_rows + 2, 50_000):
                f.write("".join(f'<row r="{n}"/>' for n in range(start, min(start + 50_000, empty_rows + 2))).encode())
            f.write(b"</sheetData></worksheet>")
        with z.open("xl/sharedStrings.xml", "w") as f:
            f.write(f"<sst {NS}>".encode())
            chunk = ("<si><t>" + "A" * 1000 + "</t></si>").encode() * 1000  # about 1 MB
            for _ in range(shared_text_mb):
                f.write(chunk)
            f.write(b"</sst>")
    return out.getvalue()


def upload(data, name="sheet.xlsx"):
    return SimpleUploadedFile(name, data)


class CheckXlsxTests(SimpleTestCase):
    def test_a_real_workbook_passes(self):
        wb = openpyxl.Workbook()
        for n in range(500):
            wb.active.append([f"ADM/{n}", f"Student {n}", n % 100])
        out = io.BytesIO()
        wb.save(out)
        file = upload(out.getvalue())
        check_xlsx(file, MARK_SHEET_MAX_UNPACKED)
        self.assertEqual(file.tell(), 0)

    def test_a_highly_compressed_part_is_refused_without_unpacking_it(self):
        bomb = raw_xlsx(shared_text_mb=30)
        self.assertLess(len(bomb), 2 * 1024 * 1024)
        start = time.monotonic()
        with self.assertRaises(UnsafeWorkbook):
            check_xlsx(upload(bomb), MARK_SHEET_MAX_UNPACKED)
        self.assertLess(time.monotonic() - start, 1)

    def test_the_total_unpacked_size_is_capped(self):
        with self.assertRaises(UnsafeWorkbook):
            check_xlsx(upload(raw_xlsx(shared_text_mb=1)), max_unpacked=100_000)

    def test_a_file_that_is_not_a_zip_is_left_to_the_importer(self):
        check_xlsx(upload(b"not a spreadsheet"), MARK_SHEET_MAX_UNPACKED)


class ImportEndpointTests(SchoolScopedAPITestCase):
    """Every Excel import refuses a bomb with a plain message, and nothing is saved."""

    def setUp(self):
        super().setUp()
        self.admin_client_a = self.authed_client(self.admin_a)

    def test_school_workbook_import(self):
        response = self.admin_client_a.post("/api/import/", {"file": upload(raw_xlsx("Students", shared_text_mb=30)),
                                                             "commit": "true"}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("unpacks to far more data", str(response.data["file"]))
        self.assertEqual(Student.objects.filter(school=self.school_a).count(), 0)

    def test_school_workbook_with_a_million_empty_rows(self):
        data = raw_xlsx("Students", header=("admission_no", "first_name"), empty_rows=310_000)
        response = self.admin_client_a.post("/api/import/", {"file": upload(data)}, format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("more than 300,000 rows", str(response.data["file"]))

    def test_staff_import(self):
        response = self.admin_client_a.post("/api/import/staff/", {"file": upload(raw_xlsx("Staff", shared_text_mb=30))},
                                            format="multipart")
        self.assertEqual(response.status_code, 400)
        self.assertIn("unpacks to far more data", str(response.data["file"]))


class PhotoTests(SchoolScopedAPITestCase):
    def setUp(self):
        super().setUp()
        self.student = Student.objects.create(school=self.school_a, first_name="Ann", last_name="X")
        self.make_admin(self.user_a)

    def post(self, data, name):
        return self.client_a.post(f"/api/students/{self.student.id}/photo/",
                                  {"photo": SimpleUploadedFile(name, data)}, format="multipart")

    def test_a_png_claiming_huge_dimensions_is_refused_before_decoding(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("1", (8000, 8000)).save(buf, format="PNG")  # 64 megapixels in a few KB
        start = time.monotonic()
        response = self.post(buf.getvalue(), "big.png")
        self.assertEqual(response.status_code, 400)
        self.assertIn("too large", str(response.data["photo"]))
        self.assertLess(time.monotonic() - start, 2)

    def test_a_large_phone_jpeg_still_works(self):
        from PIL import Image

        buf = io.BytesIO()
        Image.new("RGB", (4000, 3000), (20, 120, 200)).save(buf, format="JPEG")  # a 12 MP phone photo
        response = self.post(buf.getvalue(), "phone.jpg")
        self.assertEqual(response.status_code, 200, response.content[:200])
