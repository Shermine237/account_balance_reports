# -*- coding: utf-8 -*-
from odoo import http
from odoo.http import request


class AccountBalanceReportController(http.Controller):

    @http.route('/account_balance_reports/export/xlsx', type='json', auth='user')
    def export_xlsx(self, report_id, options):
        report = request.env['account.report'].browse(int(report_id)).exists()
        if not report:
            return {}
        return report.abr_export_xlsx(options)
