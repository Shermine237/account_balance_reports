# -*- coding: utf-8 -*-
from odoo import fields
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install')
class TestAccountBalanceReports(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.report_tb = cls.env.ref('account_balance_reports.trial_balance_report')
        cls.report_bs = cls.env.ref('account_balance_reports.balance_sheet_report')
        cls.account_receivable = cls.env['account.account'].search([
            ('company_ids', 'in', cls.env.company.id),
            ('account_type', '=', 'asset_receivable'),
        ], limit=1)
        cls.account_revenue = cls.env['account.account'].search([
            ('company_ids', 'in', cls.env.company.id),
            ('account_type', '=', 'income'),
        ], limit=1)
        cls.journal = cls.env['account.journal'].search([
            ('company_id', '=', cls.env.company.id),
            ('type', '=', 'sale'),
        ], limit=1)

    def _create_move(self, debit_account, credit_account, amount, date):
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': date,
            'journal_id': self.journal.id,
            'line_ids': [
                (0, 0, {'account_id': debit_account.id, 'debit': amount, 'credit': 0.0}),
                (0, 0, {'account_id': credit_account.id, 'debit': 0.0, 'credit': amount}),
            ],
        })
        move.action_post()
        return move

    def test_trial_balance_end_equals_initial_plus_period(self):
        if not self.account_receivable or not self.account_revenue:
            self.skipTest('Chart of accounts not fully configured')
        today = fields.Date.today()
        self._create_move(self.account_receivable, self.account_revenue, 100.0, today)
        payload = self.report_tb.abr_get_report_payload()
        rec_line = next((l for l in payload['lines'] if l.get('account_id') == self.account_receivable.id), None)
        self.assertTrue(rec_line, 'Receivable account should appear in trial balance')
        cols = {c['key']: c['no_format'] for c in rec_line['columns']}
        init_net = cols['initial_debit'] - cols['initial_credit']
        period_net = cols['debit'] - cols['credit']
        end_net = cols['end_debit'] - cols['end_credit']
        self.assertAlmostEqual(end_net, init_net + period_net, places=2)

    def test_balance_sheet_access_control(self):
        report = self.env['account.report'].create({'name': 'Unsupported'})
        with self.assertRaises(Exception):
            report.abr_get_report_payload()

    def test_warnings_for_draft_moves(self):
        if not self.account_receivable or not self.account_revenue:
            self.skipTest('Chart of accounts not fully configured')
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': fields.Date.today(),
            'journal_id': self.journal.id,
            'line_ids': [
                (0, 0, {'account_id': self.account_receivable.id, 'debit': 50.0, 'credit': 0.0}),
                (0, 0, {'account_id': self.account_revenue.id, 'debit': 0.0, 'credit': 50.0}),
            ],
        })
        payload = self.report_tb.abr_get_report_payload({'all_entries': False})
        self.assertTrue(any(w.get('type') == 'draft_moves' for w in payload.get('warnings', [])))
        move.button_cancel()

    def test_balance_sheet_has_asset_and_liability_sections(self):
        payload = self.report_bs.abr_get_report_payload()
        names = [l['name'] for l in payload['lines']]
        self.assertIn('ASSETS', names)
        self.assertIn('LIABILITIES', names)
