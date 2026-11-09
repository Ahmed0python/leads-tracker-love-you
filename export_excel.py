"""Builds the downloadable .xlsx: 'Qualified Leads' + 'Campaign Metadata' tabs."""
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook
from openpyxl.formatting.rule import CellIsRule, FormulaRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

COLUMNS = ["Company Name", "Contact Person", "Email", "Email Status", "Phone", "Website", "LinkedIn",
           "Address", "Match Score", "Priority", "Lead Source", "ICP Fit Notes", "Pitch Hook"]
SCORE_COL = COLUMNS.index("Match Score") + 1      # I
PRIO_COL = COLUMNS.index("Priority") + 1          # J
LINK_COLS = (COLUMNS.index("Website") + 1, COLUMNS.index("LinkedIn") + 1)
WRAP_COLS = (COLUMNS.index("ICP Fit Notes") + 1, COLUMNS.index("Pitch Hook") + 1)
FONT = "Arial"


def build_workbook(leads, meta):
    """leads: list of dicts keyed by COLUMNS (Match Score as 0-100). meta: dict of campaign inputs.
    Returns the .xlsx file as bytes."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Qualified Leads"

    # header
    head_fill = PatternFill("solid", fgColor="1F3864")
    for c, name in enumerate(COLUMNS, 1):
        cell = ws.cell(row=1, column=c, value=name)
        cell.font = Font(name=FONT, bold=True, color="FFFFFF", size=11)
        cell.fill = head_fill
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 28

    # rows
    for r, lead in enumerate(leads, 2):
        for c, name in enumerate(COLUMNS, 1):
            v = lead.get(name, "")
            if name == "Match Score":
                v = (v or 0) / 100
            cell = ws.cell(row=r, column=c, value=v)
            cell.font = Font(name=FONT, size=10)
            cell.alignment = Alignment(vertical="top", wrap_text=c in WRAP_COLS)
            if c == SCORE_COL:
                cell.number_format = "0%"
                cell.alignment = Alignment(horizontal="center", vertical="top")
            if c == PRIO_COL:
                cell.alignment = Alignment(horizontal="center", vertical="top")
            if c in LINK_COLS and v:
                cell.hyperlink = v
                cell.font = Font(name=FONT, size=10, color="0563C1", underline="single")
    last = max(len(leads) + 1, 2)

    # auto-fit widths (capped; long text columns get a fixed wrapped width)
    for c, name in enumerate(COLUMNS, 1):
        longest = max([len(str(name))] + [len(str(l.get(name, ""))) for l in leads])
        ws.column_dimensions[get_column_letter(c)].width = 55 if c in WRAP_COLS else min(max(longest + 3, 12), 48)
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(COLUMNS))}{last}"

    # conditional formatting: score first so it wins on its own cell
    s = get_column_letter(SCORE_COL)
    p = get_column_letter(PRIO_COL)
    ws.conditional_formatting.add(
        f"{s}2:{s}{last}",
        CellIsRule(operator="greaterThan", formula=["0.85"],
                   fill=PatternFill("solid", bgColor="63BE7B", fgColor="63BE7B"),
                   font=Font(name=FONT, bold=True, color="0B3D0B")))
    ws.conditional_formatting.add(
        f"A2:{get_column_letter(len(COLUMNS))}{last}",
        FormulaRule(formula=[f'${p}2="High"'], fill=PatternFill("solid", bgColor="E2F0D9", fgColor="E2F0D9")))

    # metadata tab
    md = wb.create_sheet("Campaign Metadata")
    rng = lambda col: f"'Qualified Leads'!{col}2:{col}{last}"
    rows = [
        ("Target Location", meta.get("location", "")),
        ("Search Range", meta.get("range", "")),
        ("Your Company", meta.get("company", "")),
        ("Product / Service", meta.get("product", "")),
        ("Campaign Type", meta.get("campaign", "")),
        ("Buyer Persona", meta.get("persona", "")),
        ("Minimum Company Size", meta.get("min_size", "")),
        ("Target Business Type", meta.get("industry", "")),
        ("Date Generated", datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("Total Leads", f"=COUNTA({rng('A')})"),
        ("High-Priority Leads", f'=COUNTIF({rng(p)},"High")'),
        ("Leads with Match Score > 85%", f'=COUNTIF({rng(s)},">0.85")'),
        ("Average Match Score", f"=IFERROR(AVERAGE({rng(s)}),0)"),
    ]
    md["A1"], md["B1"] = "Campaign Summary", ""
    md["A1"].font = Font(name=FONT, bold=True, color="FFFFFF", size=12)
    md["A1"].fill = md["B1"].fill = head_fill
    for i, (k, v) in enumerate(rows, 2):
        md.cell(row=i, column=1, value=k).font = Font(name=FONT, bold=True, size=10)
        cell = md.cell(row=i, column=2, value=v)
        cell.font = Font(name=FONT, size=10)
        cell.alignment = Alignment(horizontal="left")
    md["B14"].number_format = "0%"
    md.column_dimensions["A"].width = 32
    md.column_dimensions["B"].width = 50

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()
