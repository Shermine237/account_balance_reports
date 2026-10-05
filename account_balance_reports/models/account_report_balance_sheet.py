# -*- coding: utf-8 -*-
"""Balance Sheet specific helpers (marker model for clarity)."""
from odoo import models


class AccountReportBalanceSheet(models.AbstractModel):
    _name = 'account.report.balance.sheet'
    _description = 'Balance Sheet Report Handler'

    # Computation lives on account.report.abr_get_balance_sheet_lines
    # This model exists so abr_handler='balance_sheet' has a clear counterpart.
