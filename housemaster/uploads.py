"""
Checks on an uploaded Excel file before it is parsed.

An .xlsx file is a zip archive, and a 2 MB upload can unpack to a gigabyte (a "zip bomb"). The
importers read parts of the file into memory, so one such upload could exhaust the server and take
every school offline. The limits here are far above any real school workbook: a 3,000-student
workbook with 150,000 rows of marks and attendance unpacks to about 37 MB, at about 12 to 1.

The sizes come from the zip's own directory, so nothing is unpacked to check them. A file that
understates its sizes can't get round this: Python's zip reader stops at the stated size and
rejects the file.
"""
import zipfile

# Unpacked sizes. The mark sheet is one class and one subject; the school workbook can hold every
# student, mark and attendance record.
MARK_SHEET_MAX_UNPACKED = 20 * 1024 * 1024
WORKBOOK_MAX_UNPACKED = 60 * 1024 * 1024
# openpyxl keeps all of a workbook's shared text in memory, even when streaming the rows.
MAX_SHARED_STRINGS = 20 * 1024 * 1024
# Real spreadsheet parts compress about 5 to 20 to 1; a bomb is hundreds to 1.
MAX_RATIO = 100
MAX_PARTS = 500

TOO_BIG = ("That file unpacks to far more data than a spreadsheet of this kind should hold, so HouseMaster "
           "won't open it. Save it again as a normal .xlsx with only the sheets HouseMaster needs, or split it.")


class UnsafeWorkbook(Exception):
    pass


def check_xlsx(upload, max_unpacked):
    """
    Raise UnsafeWorkbook if the upload would unpack to more than max_unpacked bytes, or looks
    built to (a part compressed far more than a real spreadsheet compresses). Anything that isn't
    a zip is left for the importer to reject with its usual message. Leaves the file at the start.
    """
    try:
        upload.seek(0)
        try:
            infos = zipfile.ZipFile(upload).infolist()
        except (zipfile.BadZipFile, OSError, ValueError):
            return
        if len(infos) > MAX_PARTS:
            raise UnsafeWorkbook(TOO_BIG)
        total = 0
        for info in infos:
            total += info.file_size
            if info.file_size > 1024 * 1024 and info.file_size > MAX_RATIO * max(info.compress_size, 1):
                raise UnsafeWorkbook(TOO_BIG)
            if info.filename.lower().endswith("sharedstrings.xml") and info.file_size > MAX_SHARED_STRINGS:
                raise UnsafeWorkbook(TOO_BIG)
        if total > max_unpacked:
            raise UnsafeWorkbook(TOO_BIG)
    finally:
        upload.seek(0)
