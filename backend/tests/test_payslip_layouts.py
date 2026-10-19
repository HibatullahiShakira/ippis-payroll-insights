"""
Payslip layout tests, using anonymised text of real IPPIS payslip pages.

Each file in fixtures/payslip_pages is the text PyMuPDF extracts from one real
page, with names, IPPIS numbers, account numbers, PINs, TINs and dates replaced
by fakes. When IPPIS changes the layout, add a page from the new month here: the
parser then has to keep reading every layout seen so far.
"""

import pathlib
from decimal import Decimal

import pytest

from app.services.pdf_parser import _parse_page_text, _read_labelled_fields

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "payslip_pages"


def page(name):
    return _parse_page_text((FIXTURES / f"{name}.txt").read_text(encoding="utf-8"))


EXPECTED = {
    "2026_09_standard": {
        "extracted_month_year": "2026-09", "ippis_number": 900001, "name": "OKAFOR, ADAEZE NGOZI",
        "grade": "GL14_CONPSS", "step": 11, "gender": "FEMALE", "designation": "MANAGER", "tax_state": "KOGI",
        "bank_name": "Unity Bank Plc", "pfa_name": "Pension Alliance Limited",
        "account_number": "0123456789", "pension_pin": "100000000001",
        "date_of_birth": "01-JAN-1980", "date_of_first_appt": "01-JAN-2008",
        "total_gross_earnings": Decimal("359165.09"), "total_gross_deductions": Decimal("66613.13"),
        "total_net_earnings": Decimal("292551.96"),
    },
    "2026_04_standard": {
        "extracted_month_year": "2026-04", "ippis_number": 900004, "name": "EZE, CHUKWUMA PAUL",
        "grade": "GL12_CONPSS", "step": 5, "bank_name": "First City Monument Bank Plc",
        "pfa_name": "UNSPECIFIED PFA", "total_net_earnings": Decimal("23364.21"),
    },
    "2026_09_stray_backtick_in_name": {
        "ippis_number": 900003, "name": "MUSA, IBRAHIM DAUDA", "grade": "GL10_CONPSS",
        "bank_name": "First Bank of Nigeria Plc",
    },
    "2026_09_long_deductions": {
        "ippis_number": 900002, "name": "BALOGUN, TUNDE FEMI", "bank_name": "United Bank For Africa Plc",
        "pfa_name": "Premium Pension Limited", "total_gross_deductions": Decimal("275264.75"),
    },
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_fields_read_from_real_layouts(name):
    data = page(name)
    assert data is not None
    for field, value in EXPECTED[name].items():
        assert data.get(field) == value, field


@pytest.mark.parametrize("name", ["2026_09_standard", "2026_04_standard", "2026_09_stray_backtick_in_name"])
def test_figures_are_consistent(name):
    """Every payslip carries its own answer key: the items add up and Gross - Deductions = Net."""
    data = page(name)
    gross, deductions, net = (data["total_gross_earnings"], data["total_gross_deductions"],
                              data["total_net_earnings"])
    assert abs(gross - deductions - net) <= Decimal("0.05")
    assert abs(sum(i["amount"] for i in data["earnings"]) - gross) <= Decimal("0.05")
    assert abs(sum(i["amount"] for i in data["deductions"]) - deductions) <= Decimal("0.05")


def test_long_deduction_list_keeps_the_items_on_the_page():
    """The list runs past the page with no Total line; the visible items are still kept."""
    data = page("2026_09_long_deductions")
    assert len(data["deductions"]) == 20
    assert sum(i["amount"] for i in data["deductions"]) < data["total_gross_deductions"]


def test_overflow_page_is_not_a_payslip():
    assert page("2026_09_overflow_page") is None


def test_renamed_and_inline_labels_are_understood():
    """Label wording drift: other names for the same field, and value on the same line."""
    text = "\n".join([
        "EMPLOYEE PAYSLIP", "OCTOBER 2026",
        "Name of Employee", "ADE, Mr. OLU",
        "Grade Level: GL09_CONPSS",
        "IPPIS No: 123456",
        "Sex:", "MALE",
        "Bank:", "Zenith Bank", "Plc",
        "Account No.:", "1234567890",
        "RSA PIN:", "PEN100200300400",
        "Net Pay", "50,000.00",
    ])
    data = _parse_page_text(text)
    assert data["ippis_number"] == 123456
    assert data["grade"] == "GL09_CONPSS"
    assert data["gender"] == "MALE"
    assert data["bank_name"] == "Zenith Bank Plc"
    assert data["account_number"] == "1234567890"
    assert data["total_net_earnings"] == Decimal("50000.00")
    assert data["extracted_month_year"] == "2026-10"


def test_empty_fields_do_not_swallow_the_next_label():
    """'Location:' followed straight by 'TIN:' is an empty value, not the text 'TIN:'."""
    values = _read_labelled_fields("Location:\nTIN:\nDate of First Appt:\n05-DEC-2006")
    assert "location" not in values
    assert "tin" not in values
    assert values["date_of_first_appt"] == "05-DEC-2006"
