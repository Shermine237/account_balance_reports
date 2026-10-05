# -*- coding: utf-8 -*-
{
    'name': 'Accounting Balance Reports',
    'version': '18.0.3.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Enterprise-parity Balance Sheet and Trial Balance for Community',
    'description': """
Interactive Balance Sheet and Trial Balance for Odoo 18 Community.

* Full-screen report UI with filters (dates, journals, comparison, hierarchy, unfold)
* Balance Sheet with horizontal Assets | Liabilities + Equity layout
* Trial Balance with Initial / Period / End Debit & Credit columns
* Drill-down to journal items
* PDF and XLSX export
    """,
    'author': 'Charlie Rostant YOSSA',
    'phone': '+237 656 95 38 29',
    'email': 'charlieyossa@gmail.com',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'security/ir.model.access.csv',
        'data/balance_sheet.xml',
        'data/trial_balance.xml',
        'data/actions.xml',
        'views/menuitems.xml',
        'report/report_templates.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'account_balance_reports/static/src/components/account_balance_report/**/*',
            'account_balance_reports/static/src/css/account_balance_reports.css',
        ],
        'web.report_assets_common': [
            'account_balance_reports/static/src/css/account_balance_reports.css',
        ],
    },
    'installable': True,
    'application': False,
}
