"""Fill the bundled template and fit photos into the two image columns."""
from io import BytesIO
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.drawing.image import Image
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, OneCellAnchor
from openpyxl.drawing.xdr import XDRPositiveSize2D
from openpyxl.utils.units import pixels_to_EMU

TEMPLATE = Path(__file__).with_name("template.xlsx")


def set_text(cell, value):
    # Treat even values beginning with "=" as text from the form.
    cell.value = value
    cell.data_type = "s"


def make_workbook(data, layout):
    book = load_workbook(TEMPLATE)
    sheet = book["회수 완료 사진"]
    last_row = 5 + len(data["items"])
    for key, row in zip(("department", "application", "applicant"), (1, 2, 3)):
        set_text(sheet.cell(row, 3), data["header"][key])
    for merged in list(sheet.merged_cells.ranges):
        if merged.min_row > 5:
            sheet.unmerge_cells(str(merged))
    row_style = [cell._style for cell in sheet[6]]
    sheet.delete_rows(6, sheet.max_row - 5)
    for row in list(sheet.row_dimensions):
        if row > 5:
            del sheet.row_dimensions[row]

    width = layout["photoColumnPx"]
    height_pt = layout["itemRowPt"]
    height_px = round(height_pt * 96 / 72)
    # The source template groups the equally sized F and G columns.
    for key in ("F", "G"):
        if key in sheet.column_dimensions:
            del sheet.column_dimensions[key]
        sheet.column_dimensions[key].width = width / 7

    for row, item in enumerate(data["items"], 6):
        for column, style in enumerate(row_style, 1):
            sheet.cell(row, column)._style = style
        sheet.row_dimensions[row].height = height_pt
        sheet.cell(row, 1, item["order"])
        set_text(sheet.cell(row, 2), item["category"])
        set_text(sheet.cell(row, 3), item["name"])
        asset = item["asset"]
        if item["old"]:
            asset += "\n(" + item["old"] + ")"
        set_text(sheet.cell(row, 4), asset)
        sheet.cell(row, 5, item["quantity"])

        for key, column in (("photo", 5), ("sticker", 6)):
            ref = item.get(key)
            if ref is None:
                continue
            path = Path(data["directory"]) / (ref["id"] + ".jpg")
            picture = Image(path)
            scale = min((width - 16) / picture.width, (height_px - 16) / picture.height)
            w, h = max(1, round(picture.width * scale)), max(1, round(picture.height * scale))
            picture.anchor = OneCellAnchor(
                _from=AnchorMarker(col=column, row=row - 1,
                                   colOff=pixels_to_EMU((width - w) / 2),
                                   rowOff=pixels_to_EMU((height_px - h) / 2)),
                ext=XDRPositiveSize2D(cx=pixels_to_EMU(w), cy=pixels_to_EMU(h)),
            )
            sheet.add_image(picture)

    sheet.print_area = f"A1:G{last_row}"
    sheet.print_options.horizontalCentered = True
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    sheet.page_setup.orientation = sheet.ORIENTATION_LANDSCAPE
    sheet.page_setup.paperSize = sheet.PAPERSIZE_A4
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    result = BytesIO()
    book.save(result)
    return result.getvalue()
