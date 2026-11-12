from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any
from xml.sax.saxutils import escape

from openpyxl import Workbook
from openpyxl.chart import AreaChart, BarChart, DoughnutChart, LineChart, PieChart, Reference
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.worksheet.table import Table, TableStyleInfo
from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.charts.piecharts import Pie
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)
from reportlab.platypus import (
    Table as PDFTable,
)

from app.schemas.dashboard import DashboardResponse, DashboardWidget


def export_dashboard(
    dashboard: DashboardResponse,
    export_format: str,
    selected_filters: dict[str, str],
) -> tuple[bytes, str, str]:
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", dashboard.title).strip("_")[:80] or "dashboard"
    if export_format == "xlsx":
        return (
            build_excel(dashboard, selected_filters),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            f"{safe_title}.xlsx",
        )
    if export_format == "pdf":
        return build_pdf(dashboard, selected_filters), "application/pdf", f"{safe_title}.pdf"
    raise ValueError("Export format must be xlsx or pdf")


def build_excel(
    dashboard: DashboardResponse, selected_filters: dict[str, str]
) -> bytes:
    workbook = Workbook()
    overview = workbook.active
    overview.title = "Overview"
    overview.sheet_view.showGridLines = False
    overview.merge_cells("A1:F1")
    overview["A1"] = _excel_text(dashboard.title)
    overview["A1"].font = Font(size=20, bold=True, color="FFFFFF")
    overview["A1"].fill = PatternFill("solid", fgColor="282247")
    overview["A1"].alignment = Alignment(vertical="center")
    overview.row_dimensions[1].height = 34
    overview["A2"] = _excel_text(dashboard.description)
    overview["A3"] = "Business question"
    overview["B3"] = _excel_text(dashboard.question)
    overview["A4"] = "Database ID"
    overview["B4"] = str(dashboard.database_id)
    overview["A5"] = "Company mapping ID"
    overview["B5"] = str(dashboard.company_mapping_id or "Database default")

    row = 7
    overview.cell(row, 1, "Dashboard filters").font = Font(bold=True, color="FFFFFF")
    overview.cell(row, 1).fill = PatternFill("solid", fgColor="514785")
    row += 1
    for item in dashboard.filters:
        overview.cell(row, 1, _excel_text(item.label))
        overview.cell(row, 2, _excel_text(selected_filters.get(item.filter_id, "All")))
        overview.cell(row, 3, f"Available options: {', '.join(item.options)}")
        row += 1

    row += 1
    overview.cell(row, 1, "KPI summary").font = Font(bold=True, color="FFFFFF")
    overview.cell(row, 1).fill = PatternFill("solid", fgColor="514785")
    row += 1
    for widget in dashboard.widgets:
        if widget.visualization != "kpi":
            continue
        metric = widget.value_field or (widget.columns[0] if widget.columns else "Value")
        value = widget.rows[0].get(metric) if widget.rows else None
        overview.cell(row, 1, _excel_text(widget.title))
        overview.cell(row, 2, _excel_text(metric))
        overview.cell(row, 3, _excel_value(value, numeric=True))
        overview.cell(row, 4, "No result" if value is None else "")
        row += 1
    for cell in overview[7]:
        cell.font = Font(bold=True, color="FFFFFF")
    overview.column_dimensions["A"].width = 30
    overview.column_dimensions["B"].width = 34
    overview.column_dimensions["C"].width = 52
    overview.column_dimensions["D"].width = 18
    overview.freeze_panes = "A7"

    used_names = {"overview"}
    for index, widget in enumerate(dashboard.widgets, start=1):
        sheet_name = _sheet_name(widget.title, index, used_names)
        sheet = workbook.create_sheet(sheet_name)
        sheet.sheet_view.showGridLines = False
        sheet.cell(1, 1, _excel_text(widget.title)).font = Font(size=15, bold=True)
        sheet.cell(2, 1, f"Visualization: {widget.visualization}")
        sheet.cell(3, 1, f"Question: {widget.question}")
        sheet.cell(4, 1, f"Validated query: {widget.sql}")
        header_row = 6
        for column_index, column in enumerate(widget.columns, start=1):
            cell = sheet.cell(header_row, column_index, _excel_text(column))
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="514785")
        for row_index, result_row in enumerate(widget.rows, start=header_row + 1):
            for column_index, column in enumerate(widget.columns, start=1):
                is_metric = column == widget.value_field
                sheet.cell(
                    row_index,
                    column_index,
                    _excel_value(result_row.get(column), numeric=is_metric),
                )
        if widget.columns and widget.rows:
            table = Table(
                displayName=f"WidgetData{index}",
                ref=f"A{header_row}:{_column_letter(len(widget.columns))}{header_row + len(widget.rows)}",
            )
            table.tableStyleInfo = TableStyleInfo(
                name="TableStyleMedium2",
                showFirstColumn=False,
                showLastColumn=False,
                showRowStripes=True,
                showColumnStripes=False,
            )
            sheet.add_table(table)
            sheet.freeze_panes = f"A{header_row + 1}"
        for column_index, column in enumerate(widget.columns, start=1):
            sheet.column_dimensions[_column_letter(column_index)].width = min(
                32, max(14, len(column) + 3)
            )
        _add_excel_chart(sheet, widget, header_row)
        if widget.truncated:
            sheet.cell(5, 1, "Query results were capped by the safe row limit.")

    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def build_pdf(
    dashboard: DashboardResponse, selected_filters: dict[str, str]
) -> bytes:
    output = BytesIO()
    page_size = landscape(letter)
    margin = 0.42 * inch
    document = SimpleDocTemplate(
        output,
        pagesize=page_size,
        rightMargin=margin,
        leftMargin=margin,
        topMargin=margin,
        bottomMargin=margin,
        title=dashboard.title,
        author="InsightGPT AI",
    )
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DashboardTitle", parent=styles["Title"], alignment=TA_LEFT, textColor=colors.HexColor("#282247")
    )
    body_style = ParagraphStyle("DashboardBody", parent=styles["BodyText"], fontSize=8, leading=11)
    small_style = ParagraphStyle("DashboardSmall", parent=body_style, fontSize=6.5, leading=8)
    story: list[Any] = [
        Paragraph(escape(dashboard.title), title_style),
        Paragraph(escape(dashboard.description or ""), body_style),
        Spacer(1, 8),
        Paragraph(f"Business question: {escape(dashboard.question)}", body_style),
        Paragraph(f"Database: {dashboard.database_id} · Company mapping: {dashboard.company_mapping_id or 'Default'}", small_style),
        Spacer(1, 12),
    ]

    filter_data = [["Filter", "Selected value", "Available values"]]
    filter_data.extend(
        [
            [
                _paragraph(item.label, small_style),
                _paragraph(selected_filters.get(item.filter_id, "All"), small_style),
                _paragraph(", ".join(item.options) or "No options", small_style),
            ]
            for item in dashboard.filters
        ]
    )
    if len(filter_data) > 1:
        story.extend([Paragraph("Filters", styles["Heading2"]), _pdf_table(filter_data, document.width), Spacer(1, 10)])

    kpi_widgets = [widget for widget in dashboard.widgets if widget.visualization == "kpi"]
    if kpi_widgets:
        kpi_data = [["KPI", "Metric", "Value"]]
        for widget in kpi_widgets:
            metric = widget.value_field or (widget.columns[0] if widget.columns else "Value")
            value = widget.rows[0].get(metric) if widget.rows else None
            kpi_data.append([
                _paragraph(widget.title, small_style),
                _paragraph(metric, small_style),
                _paragraph(_display(value), body_style),
            ])
        story.extend([Paragraph("Key performance indicators", styles["Heading2"]), _pdf_table(kpi_data, document.width), Spacer(1, 12)])

    for index, widget in enumerate(dashboard.widgets, start=1):
        story.append(Paragraph(escape(widget.title), styles["Heading2"]))
        story.append(Paragraph(f"{escape(widget.visualization.title())} · {len(widget.rows)} rows", small_style))
        chart = _pdf_chart(widget, document.width)
        if chart is not None:
            story.extend([chart, Spacer(1, 6)])
        story.append(Paragraph("Detailed data", styles["Heading3"]))
        headers = widget.columns or ["Result"]
        table_data = [[_paragraph(column, small_style) for column in headers]]
        for result in widget.rows:
            table_data.append(
                [
                    _paragraph(_display(result.get(column)), small_style)
                    for column in headers
                ]
            )
        if len(table_data) == 1:
            table_data.append([_paragraph("No rows returned.", small_style)] + [""] * (len(headers) - 1))
        story.append(_pdf_table(table_data, document.width))
        if index < len(dashboard.widgets):
            story.append(PageBreak())
    document.build(story)
    return output.getvalue()


def _add_excel_chart(sheet, widget: DashboardWidget, header_row: int) -> None:
    if widget.visualization not in {"bar", "line", "area", "pie", "donut"}:
        return
    if not widget.rows or not widget.category_field or not widget.value_field:
        return
    try:
        category_column = widget.columns.index(widget.category_field) + 1
        value_column = widget.columns.index(widget.value_field) + 1
    except ValueError:
        return
    categories = Reference(
        sheet, min_col=category_column, min_row=header_row + 1, max_row=header_row + len(widget.rows)
    )
    data = Reference(
        sheet, min_col=value_column, min_row=header_row, max_row=header_row + len(widget.rows)
    )
    chart_class = {
        "bar": BarChart,
        "line": LineChart,
        "area": AreaChart,
        "pie": PieChart,
        "donut": DoughnutChart,
    }[widget.visualization]
    chart = chart_class()
    chart.title = widget.title
    chart.add_data(data, titles_from_data=True)
    chart.set_categories(categories)
    chart.height = 8
    chart.width = 15
    if widget.visualization == "bar":
        chart.type = "bar"
        chart.style = 10
    sheet.add_chart(chart, "J2")


def _pdf_chart(widget: DashboardWidget, width: float):
    if widget.visualization not in {"bar", "line", "area", "pie", "donut"}:
        return None
    if not widget.rows or not widget.category_field or not widget.value_field:
        return None
    labels = [_display(row.get(widget.category_field))[:24] for row in widget.rows[:24]]
    values = [_number(row.get(widget.value_field)) for row in widget.rows[:24]]
    if not any(value is not None for value in values):
        return None
    values = [value or 0.0 for value in values]
    drawing = Drawing(width, 2.25 * inch)
    if widget.visualization in {"pie", "donut"}:
        chart = Pie()
        chart.x = 80
        chart.y = 14
        chart.width = min(180, width * 0.38)
        chart.height = min(150, 1.85 * inch)
        chart.data = values
        chart.labels = labels
        chart.slices.strokeColor = colors.white
        chart.slices.strokeWidth = 0.5
        if widget.visualization == "donut":
            chart.innerRadius = 45
        drawing.add(chart)
        return drawing
    if widget.visualization == "line":
        chart = HorizontalLineChart()
        chart.x = 42
        chart.y = 26
        chart.width = width - 65
        chart.height = 1.7 * inch
        chart.data = [values]
        chart.categoryAxis.categoryNames = labels
        chart.categoryAxis.labels.angle = 25
        chart.categoryAxis.labels.fontSize = 6
        chart.valueAxis.valueMin = min(0, min(values))
        chart.lines[0].strokeColor = colors.HexColor("#6D5BD0")
        chart.lines[0].strokeWidth = 2
        drawing.add(chart)
        return drawing
    chart = VerticalBarChart()
    chart.x = 42
    chart.y = 30
    chart.width = width - 65
    chart.height = 1.65 * inch
    chart.data = [values]
    chart.categoryAxis.categoryNames = labels
    chart.categoryAxis.labels.angle = 25
    chart.categoryAxis.labels.fontSize = 6
    chart.categoryAxis.labels.boxAnchor = "ne"
    chart.valueAxis.valueMin = min(0, min(values))
    chart.bars[0].fillColor = colors.HexColor("#6D5BD0")
    drawing.add(chart)
    return drawing


def _pdf_table(data: list[list[Any]], width: float) -> PDFTable:
    columns = max(1, max(len(row) for row in data))
    table = PDFTable(data, repeatRows=1, colWidths=[width / columns] * columns, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#282247")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#D9D7E2")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F5F4F8")]),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    return table


def _paragraph(value: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(_display(value)), style)


def _excel_value(value: object, *, numeric: bool = False):
    if value is None:
        return None
    if isinstance(value, (datetime, date, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value) if numeric else str(value)
    if numeric:
        parsed = _number(value)
        if parsed is not None:
            return parsed
    return _excel_text(str(value))


def _excel_text(value: str) -> str:
    dangerous = value.lstrip(" \t\r\n")
    return "'" + value if dangerous.startswith(("=", "+", "-", "@")) else value


def _number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).replace(",", ""))
    except (ValueError, InvalidOperation):
        return None
    return result if math.isfinite(result) else None


def _display(value: object) -> str:
    if value is None:
        return "—"
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, (dict, list, tuple)):
        return str(value)
    return str(value)


def _sheet_name(title: str, index: int, used: set[str]) -> str:
    value = re.sub(r"[\\/*?:\[\]]", "_", title).strip(" '")[:25] or f"Widget{index}"
    base = value
    suffix = 1
    while value.casefold() in used:
        value = f"{base[:25 - len(str(suffix))]}_{suffix}"
        suffix += 1
    used.add(value.casefold())
    return value


def _column_letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index)
