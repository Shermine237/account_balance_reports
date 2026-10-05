# -*- coding: utf-8 -*-
import base64
import io
import json

from odoo import api, fields, models, _
from odoo.tools.misc import xlsxwriter


class AccountBalanceReportExport(models.TransientModel):
    _name = 'account.balance.report.export'
    _description = 'Accounting Balance Report Export'

    report_id = fields.Many2one('account.report', required=True, ondelete='cascade')
    options_json = fields.Text()
    xlsx_file = fields.Binary()
    xlsx_filename = fields.Char()

    def _get_payload(self):
        self.ensure_one()
        options = json.loads(self.options_json or '{}')
        return self.report_id.with_context(active_test=True).abr_get_report_payload(options)

    def _generate_xlsx(self, payload=None):
        self.ensure_one()
        payload = payload or self._get_payload()
        options = payload['options']
        lines = payload['lines']
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet(payload.get('report_name') or 'Report')
        header = workbook.add_format({'bold': True, 'bg_color': '#D9E1F2'})
        bold = workbook.add_format({'bold': True})
        money = workbook.add_format({'num_format': '#,##0.00'})

        sheet.write(0, 0, payload.get('report_name') or '', bold)
        sheet.write(1, 0, '%s → %s' % (options.get('date_from'), options.get('date_to')))

        row = 3
        sheet.write(row, 0, _('Code'), header)
        sheet.write(row, 1, _('Label'), header)
        for col_idx, col in enumerate(options.get('columns') or [], start=2):
            sheet.write(row, col_idx, col.get('name') or '', header)

        for line in lines:
            row += 1
            sheet.write(row, 0, line.get('code') or '')
            indent = '  ' * int(line.get('level') or 0)
            sheet.write(row, 1, indent + (line.get('name') or ''), bold if line.get('class') else None)
            for col_idx, col in enumerate(line.get('columns') or [], start=2):
                sheet.write_number(row, col_idx, col.get('no_format') or 0.0, money)

        workbook.close()
        data = output.getvalue()
        filename = '%s.xlsx' % (payload.get('report_name') or 'report').replace(' ', '_')
        self.write({
            'xlsx_file': base64.b64encode(data),
            'xlsx_filename': filename,
        })
        return True
