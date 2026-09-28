"""
Every workbook the app writes adds its rows through append_row(), so text
that looks like a formula (it starts with =, +, -, @, a tab or a carriage
return) is stored as plain text and can never run when someone opens the
file. openpyxl would otherwise store "=..." as a live formula.

(The app writes no CSV files. If one is added, prefix such values with an
apostrophe instead.)
"""
RISKY_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def append_row(ws, values):
    values = list(values)
    ws.append(values)
    row = ws._current_row
    for column, value in enumerate(values, start=1):
        if isinstance(value, str) and value.startswith(RISKY_PREFIXES):
            ws.cell(row=row, column=column).data_type = "s"
