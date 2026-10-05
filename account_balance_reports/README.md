# Accounting Balance Reports (Odoo 18 Community)

Interactive **Balance Sheet** and **Trial Balance** for Odoo 18 Community.

## Menus

- **Invoicing → Reporting → Statement Reports → Balance Sheet**
- **Invoicing → Reporting → Audit Reports → Trial Balance**

## Features

- Enterprise-like filter bar (dates, journals, analytic, comparison, posted/draft)
- Draft entries warning banner
- Trial Balance: Initial / Period / End (Debit & Credit)
- Balance Sheet: horizontal Assets | Liabilities + Equity
- Drill-down to journal items per column
- PDF and XLSX export
- French translations (`i18n/fr.po`)

## Install

1. Add this folder to your Odoo addons path
2. Update Apps list
3. Install **Accounting Balance Reports**
4. Upgrade module if already installed (`-u account_balance_reports`)

## Tests

```bash
odoo-bin -d YOUR_DB -i account_balance_reports --test-enable --stop-after-init
```
