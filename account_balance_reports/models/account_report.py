# -*- coding: utf-8 -*-
import ast
import json
import re
from dateutil.relativedelta import relativedelta

from odoo import fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.tools import float_is_zero

AGG_TOKEN_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)')

OPTIONS_KEYS = {
    'date_filter', 'date_from', 'date_to', 'all_entries', 'journal_ids', 'company_ids',
    'hierarchy', 'hide_zero_lines', 'unfold_all', 'unfolded_lines', 'comparison',
    'search_value', 'analytic_account_ids',
}


class AccountReport(models.Model):
    _inherit = 'account.report'

    abr_handler = fields.Selection(
        selection=[
            ('balance_sheet', 'Balance Sheet'),
            ('trial_balance', 'Trial Balance'),
        ],
        string='Community Report Handler',
    )

    # -------------------------------------------------------------------------
    # Access control
    # -------------------------------------------------------------------------

    def _abr_check_access(self):
        self.ensure_one()
        if not self.abr_handler:
            raise UserError(_('This report is not supported by Accounting Balance Reports.'))
        if not self.env.user.has_group('account.group_account_readonly') and not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(_('You do not have access to accounting reports.'))

    def _abr_sanitize_previous_options(self, previous_options):
        if not previous_options:
            return {}
        return {k: v for k, v in previous_options.items() if k in OPTIONS_KEYS}

    # -------------------------------------------------------------------------
    # Public RPC API
    # -------------------------------------------------------------------------

    def abr_get_report_payload(self, options=None):
        self.ensure_one()
        self._abr_check_access()
        options = self.abr_get_options(options or {})
        if self.abr_handler == 'trial_balance':
            lines = self.env['account.report.trial.balance'].abr_get_lines(self, options)
        else:
            lines = self.abr_get_balance_sheet_lines(options)
        return {
            'options': options,
            'lines': lines,
            'report_name': self.name,
            'handler': self.abr_handler,
            'warnings': options.get('warnings', []),
        }

    def abr_open_journal_items(self, options, line_id, column_key=None):
        self.ensure_one()
        self._abr_check_access()
        options = self.abr_get_options(self._abr_sanitize_previous_options(options or {}))
        domain = self._abr_base_aml_domain(options)
        domain = [d for d in domain if not (isinstance(d, tuple) and d[0] == 'date')]
        domain += self._abr_date_domain_for_column(options, column_key)

        parsed = self._abr_parse_line_id(line_id)
        if parsed.get('account_id'):
            domain.append(('account_id', '=', parsed['account_id']))
        elif parsed.get('account_group_id'):
            domain.append(('account_id.group_id', 'child_of', parsed['account_group_id']))
        elif parsed.get('report_line_id'):
            report_line = self.env['account.report.line'].browse(parsed['report_line_id'])
            account_domain = self._abr_account_domain_from_line(report_line, options)
            accounts = self.env['account.account'].search(account_domain) if account_domain else self.env['account.account']
            domain.append(('account_id', 'in', accounts.ids))
        else:
            domain.append(('id', '=', False))

        return {
            'type': 'ir.actions.act_window',
            'name': _('Journal Items'),
            'res_model': 'account.move.line',
            'view_mode': 'list,form',
            'domain': domain,
            'context': {'search_default_group_by_account': 1},
        }

    def abr_export_xlsx(self, options=None):
        self.ensure_one()
        self._abr_check_access()
        options = self.abr_get_options(self._abr_sanitize_previous_options(options or {}))
        payload = self.abr_get_report_payload(options)
        export = self.env['account.balance.report.export'].create({
            'report_id': self.id,
            'options_json': json.dumps(options),
        })
        export._generate_xlsx(payload)
        return {
            'type': 'ir.actions.act_url',
            'url': '/web/content/?model=account.balance.report.export&id=%s&field=xlsx_file&filename_field=xlsx_filename&download=true' % export.id,
            'target': 'self',
        }

    def abr_export_pdf(self, options=None):
        self.ensure_one()
        self._abr_check_access()
        options = self.abr_get_options(self._abr_sanitize_previous_options(options or {}))
        export = self.env['account.balance.report.export'].create({
            'report_id': self.id,
            'options_json': json.dumps(options),
        })
        return self.env.ref('account_balance_reports.action_report_abr_pdf').report_action(export)

    # -------------------------------------------------------------------------
    # Options
    # -------------------------------------------------------------------------

    def abr_get_options(self, previous_options=None):
        self.ensure_one()
        previous_options = self._abr_sanitize_previous_options(previous_options)
        company = self._abr_get_main_company(previous_options)
        today = fields.Date.context_today(self)

        date_filter = previous_options.get('date_filter') or self.default_opening_date_filter or 'this_month'
        date_from, date_to = self._abr_dates_from_filter(date_filter, today, company)
        if previous_options.get('date_from'):
            date_from = fields.Date.to_date(previous_options['date_from'])
        if previous_options.get('date_to'):
            date_to = fields.Date.to_date(previous_options['date_to'])
        if not self.filter_date_range:
            date_from = date_to

        comparison = previous_options.get('comparison') or {'filter': 'no_comparison', 'number_period': 1}
        comparison_periods = self._abr_comparison_periods(date_from, date_to, comparison, company)

        company_ids = self._abr_resolve_company_ids(previous_options)
        journals = self.env['account.journal'].search([('company_id', 'in', company_ids)])

        hierarchy = previous_options.get('hierarchy')
        if hierarchy is None:
            hierarchy = self.filter_hierarchy == 'by_default'

        hide_zero = previous_options.get('hide_zero_lines')
        if hide_zero is None:
            hide_zero = self.filter_hide_0_lines == 'by_default'

        unfold_all = bool(previous_options.get('unfold_all', False))
        unfolded_lines = list(previous_options.get('unfolded_lines') or [])

        options = {
            'report_id': self.id,
            'handler': self.abr_handler,
            'date_filter': date_filter,
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'filter_date_range': bool(self.filter_date_range),
            'all_entries': bool(previous_options.get('all_entries', False)),
            'journal_ids': previous_options.get('journal_ids') or [],
            'available_journals': [{'id': j.id, 'name': j.display_name} for j in journals],
            'company_ids': company_ids,
            'available_companies': [
                {'id': c.id, 'name': c.name}
                for c in self.env['res.company'].search([('id', 'in', self.env.companies.ids)])
            ],
            'multi_company': self.filter_multi_company == 'selector',
            'hierarchy': bool(hierarchy),
            'filter_hierarchy': self.filter_hierarchy or 'optional',
            'hide_zero_lines': bool(hide_zero),
            'filter_hide_0_lines': self.filter_hide_0_lines or 'optional',
            'unfold_all': unfold_all,
            'unfolded_lines': unfolded_lines,
            'comparison': comparison,
            'comparison_periods': comparison_periods,
            'filter_period_comparison': bool(self.filter_period_comparison),
            'filter_journals': bool(self.filter_journals),
            'filter_unfold_all': bool(self.filter_unfold_all),
            'search_bar': bool(self.search_bar),
            'search_value': previous_options.get('search_value') or '',
            'horizontal_split': self.abr_handler != 'trial_balance',
            'currency_id': company.currency_id.id,
            'currency_symbol': company.currency_id.symbol,
            'currency_name': company.currency_id.name,
            'currency_position': company.currency_id.position,
            'decimal_places': company.currency_id.decimal_places,
        }

        has_analytic = 'analytic.account' in self.env
        options['filter_analytic'] = bool(self.filter_analytic and has_analytic)
        options['analytic_account_ids'] = previous_options.get('analytic_account_ids') or []
        if options['filter_analytic']:
            options['available_analytic_accounts'] = [
                {'id': a.id, 'name': a.display_name}
                for a in self.env['analytic.account'].search([
                    ('company_id', 'in', company_ids + [False]),
                ], limit=500)
            ]

        options['columns'] = self._abr_build_columns(options)
        options['warnings'] = self._abr_get_warnings(options)
        return options

    def _abr_resolve_company_ids(self, previous_options):
        if self.filter_multi_company == 'selector':
            ids = previous_options.get('company_ids') or self.env.companies.ids
        else:
            ids = [self.env.company.id]
        return self.env['res.company'].browse(ids).exists().ids

    def _abr_get_main_company(self, options):
        company_ids = self._abr_resolve_company_ids(options)
        return self.env['res.company'].browse(company_ids[0]) if company_ids else self.env.company

    def _abr_get_warnings(self, options):
        warnings = []
        if options.get('all_entries'):
            return warnings
        company_ids = self._abr_company_ids(options)
        date_to = fields.Date.to_date(options['date_to'])
        date_from = fields.Date.to_date(options['date_from'])
        draft_count = self.env['account.move'].search_count([
            ('company_id', 'in', company_ids),
            ('state', '=', 'draft'),
            ('date', '<=', date_to),
            ('date', '>=', date_from if options.get('filter_date_range') else '1900-01-01'),
        ])
        if draft_count:
            warnings.append({
                'type': 'draft_moves',
                'message': _('There are unposted journal entries prior to or included in this period.'),
            })
        return warnings

    def _abr_dates_from_filter(self, date_filter, today, company):
        if date_filter == 'today':
            return today, today
        if date_filter == 'this_month':
            start = today.replace(day=1)
            return start, start + relativedelta(months=1, days=-1)
        if date_filter == 'previous_month':
            end = today.replace(day=1) - relativedelta(days=1)
            return end.replace(day=1), end
        if date_filter == 'this_quarter':
            quarter = (today.month - 1) // 3
            start = today.replace(month=quarter * 3 + 1, day=1)
            return start, start + relativedelta(months=3, days=-1)
        if date_filter == 'previous_quarter':
            this_q_start = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
            end = this_q_start - relativedelta(days=1)
            return end.replace(month=((end.month - 1) // 3) * 3 + 1, day=1), end
        if date_filter == 'this_year':
            fy = company.compute_fiscalyear_dates(today)
            return fy['date_from'], fy['date_to']
        if date_filter == 'previous_year':
            fy = company.compute_fiscalyear_dates(today)
            prev_day = fy['date_from'] - relativedelta(days=1)
            prev_fy = company.compute_fiscalyear_dates(prev_day)
            return prev_fy['date_from'], prev_fy['date_to']
        start = today.replace(day=1)
        return start, start + relativedelta(months=1, days=-1)

    def _abr_comparison_periods(self, date_from, date_to, comparison, company):
        filter_name = comparison.get('filter') or 'no_comparison'
        number = int(comparison.get('number_period') or 1)
        periods = []
        if filter_name == 'no_comparison' or number <= 0:
            return periods
        delta_days = (date_to - date_from).days + 1
        cursor_from, cursor_to = date_from, date_to
        for _i in range(number):
            if filter_name == 'same_last_period':
                cursor_to = cursor_from - relativedelta(days=1)
                cursor_from = cursor_to - relativedelta(days=delta_days - 1)
            elif filter_name == 'same_last_year':
                cursor_from = cursor_from - relativedelta(years=1)
                cursor_to = cursor_to - relativedelta(years=1)
            else:
                break
            periods.append({
                'date_from': fields.Date.to_string(cursor_from),
                'date_to': fields.Date.to_string(cursor_to),
                'string': '%s - %s' % (cursor_from, cursor_to),
            })
        return periods

    def _abr_period_label(self, options):
        date_from = fields.Date.to_date(options['date_from'])
        date_to = fields.Date.to_date(options['date_to'])
        if date_from.year == date_to.year and date_from.month == 1 and date_from.day == 1 and date_to.month == 12 and date_to.day == 31:
            return str(date_to.year)
        if date_from == date_to:
            return fields.Date.to_string(date_to)
        return '%s - %s' % (date_from, date_to)

    def _abr_build_columns(self, options):
        if options.get('handler') == 'trial_balance':
            columns = [
                {'name': _('Debit'), 'key': 'initial_debit', 'group': _('Initial Balance'), 'scope': 'initial'},
                {'name': _('Credit'), 'key': 'initial_credit', 'group': _('Initial Balance'), 'scope': 'initial'},
                {'name': _('Debit'), 'key': 'debit', 'group': self._abr_period_label(options), 'scope': 'period'},
                {'name': _('Credit'), 'key': 'credit', 'group': self._abr_period_label(options), 'scope': 'period'},
            ]
            for idx, period in enumerate(options.get('comparison_periods') or []):
                columns += [
                    {'name': _('Debit'), 'key': 'comp_%s_debit' % idx, 'group': period['string'], 'scope': 'comparison', 'comparison_index': idx},
                    {'name': _('Credit'), 'key': 'comp_%s_credit' % idx, 'group': period['string'], 'scope': 'comparison', 'comparison_index': idx},
                ]
            columns += [
                {'name': _('Debit'), 'key': 'end_debit', 'group': _('End Balance'), 'scope': 'end'},
                {'name': _('Credit'), 'key': 'end_credit', 'group': _('End Balance'), 'scope': 'end'},
            ]
            return columns

        columns = [{'name': _('Balance'), 'key': 'balance', 'group': self._abr_period_label(options), 'scope': 'end'}]
        for idx, period in enumerate(options.get('comparison_periods') or []):
            columns.append({
                'name': _('Balance'),
                'key': 'comp_%s_balance' % idx,
                'group': period['string'],
                'scope': 'comparison',
                'comparison_index': idx,
            })
        return columns

    def _abr_date_domain_for_column(self, options, column_key):
        if not column_key:
            date_to = fields.Date.to_date(options['date_to'])
            return [('date', '<=', date_to)]

        date_from = fields.Date.to_date(options['date_from'])
        date_to = fields.Date.to_date(options['date_to'])

        if column_key in ('initial_debit', 'initial_credit'):
            return [('date', '<', date_from)]
        if column_key in ('debit', 'credit'):
            return [('date', '>=', date_from), ('date', '<=', date_to)]
        if column_key in ('end_debit', 'end_credit', 'balance'):
            return [('date', '<=', date_to)]
        if column_key.startswith('comp_'):
            parts = column_key.split('_')
            if len(parts) >= 3 and parts[1].isdigit():
                idx = int(parts[1])
                periods = options.get('comparison_periods') or []
                if idx < len(periods):
                    p = periods[idx]
                    return [
                        ('date', '>=', fields.Date.to_date(p['date_from'])),
                        ('date', '<=', fields.Date.to_date(p['date_to'])),
                    ]
        return [('date', '<=', date_to)]

    # -------------------------------------------------------------------------
    # Domains / balances helpers
    # -------------------------------------------------------------------------

    def _abr_company_ids(self, options):
        if isinstance(options, dict):
            return options.get('company_ids') or [self.env.company.id]
        return options or [self.env.company.id]

    def _abr_base_aml_domain(self, options, date_from=None, date_to=None, strict_range=False):
        company_ids = self._abr_company_ids(options)
        domain = [
            ('parent_state', '!=', 'cancel'),
            ('display_type', 'not in', ('line_section', 'line_note')),
            ('company_id', 'in', company_ids),
        ]
        if not options.get('all_entries'):
            domain.append(('parent_state', '=', 'posted'))
        if options.get('journal_ids'):
            domain.append(('journal_id', 'in', options['journal_ids']))
        analytic_ids = options.get('analytic_account_ids') or []
        if analytic_ids:
            domain.append(('analytic_distribution', 'in', analytic_ids))
        if date_to:
            domain.append(('date', '<=', date_to))
        if date_from and strict_range:
            domain.append(('date', '>=', date_from))
        return domain

    def _abr_read_group_balances(self, domain):
        groups = self.env['account.move.line']._read_group(
            domain,
            groupby=['account_id'],
            aggregates=['debit:sum', 'credit:sum', 'balance:sum'],
        )
        result = {}
        for account, debit, credit, balance in groups:
            if account:
                result[account.id] = {
                    'debit': debit or 0.0,
                    'credit': credit or 0.0,
                    'balance': balance or 0.0,
                }
        return result

    def _abr_aggregate_balance(self, domain):
        groups = self.env['account.move.line']._read_group(
            domain, groupby=[], aggregates=['balance:sum'],
        )
        if not groups:
            return 0.0
        return groups[0][0] or 0.0

    def _abr_account_company_domain(self, options):
        company_ids = self._abr_company_ids(options)
        if len(company_ids) == 1:
            return [
                '|',
                ('company_ids', 'parent_of', company_ids[0]),
                ('company_ids', 'child_of', company_ids[0]),
            ]
        return [('company_ids', 'in', company_ids)]

    def _abr_split_debit_credit(self, balance, currency):
        if currency.compare_amounts(balance, 0.0) > 0:
            return balance, 0.0
        if currency.compare_amounts(balance, 0.0) < 0:
            return 0.0, abs(balance)
        return 0.0, 0.0

    def _abr_parse_line_id(self, line_id):
        result = {}
        if not line_id:
            return result
        parts = str(line_id).split('_')
        i = 0
        while i < len(parts):
            if parts[i] == 'report' and i + 2 < len(parts) and parts[i + 1] == 'line':
                result['report_line_id'] = int(parts[i + 2])
                i += 3
            elif parts[i] == 'account' and i + 1 < len(parts):
                result['account_id'] = int(parts[i + 1])
                i += 2
            elif parts[i] == 'group' and i + 1 < len(parts):
                result['account_group_id'] = int(parts[i + 1])
                i += 2
            else:
                i += 1
        return result

    def _abr_account_domain_from_line(self, report_line, options):
        for expr in report_line.expression_ids.filtered(lambda e: e.engine == 'domain'):
            try:
                formula = ast.literal_eval(expr.formula)
            except Exception:
                continue
            account_domain = []
            skip = False
            for token in formula:
                if token in ('|', '&', '!'):
                    account_domain.append(token)
                elif isinstance(token, (list, tuple)) and len(token) == 3:
                    field, op, val = token
                    if field.startswith('account_id.'):
                        account_domain.append((field[len('account_id.'):], op, val))
                    elif field == 'account_id':
                        account_domain.append(('id', op, val))
                    else:
                        skip = True
                        break
                else:
                    skip = True
                    break
            if not skip and account_domain:
                return self._abr_account_company_domain(options) + account_domain
        return []

    # -------------------------------------------------------------------------
    # Balance Sheet computation
    # -------------------------------------------------------------------------

    def abr_get_balance_sheet_lines(self, options):
        self.ensure_one()
        company = self._abr_get_main_company(options)
        currency = company.currency_id
        unfolded = set(options.get('unfolded_lines') or [])
        unfold_all = options.get('unfold_all')

        period_specs = [{'key_prefix': '', 'date_from': options['date_from'], 'date_to': options['date_to']}]
        for idx, period in enumerate(options.get('comparison_periods') or []):
            period_specs.append({
                'key_prefix': 'comp_%s_' % idx,
                'date_from': period['date_from'],
                'date_to': period['date_to'],
            })

        expression_cache = {}
        line_values = {}

        def eval_domain_expression(expr, date_from, date_to):
            cache_key = (expr.id, date_from, date_to, tuple(options.get('journal_ids') or ()), tuple(options.get('company_ids') or ()))
            if cache_key in expression_cache:
                return expression_cache[cache_key]
            try:
                ml_domain = ast.literal_eval(expr.formula)
            except Exception:
                expression_cache[cache_key] = 0.0
                return 0.0
            aml_domain = self._abr_base_aml_domain(options)
            aml_domain = [d for d in aml_domain if not (isinstance(d, tuple) and d[0] == 'date')]
            scope = expr.date_scope or 'strict_range'
            if scope == 'strict_range' and not options.get('filter_date_range'):
                scope = 'from_beginning'
            d_from = fields.Date.to_date(date_from)
            d_to = fields.Date.to_date(date_to)
            aml_domain += self._abr_scope_date_domain(scope, d_from, d_to, company)
            aml_domain += ml_domain
            balance = self._abr_aggregate_balance(aml_domain)
            if (expr.subformula or 'sum') == '-sum':
                balance = -balance
            expression_cache[cache_key] = balance
            return balance

        def get_expr_value(line_code, label, date_from, date_to):
            line = self.line_ids.filtered(lambda l: l.code == line_code)[:1]
            if not line:
                return 0.0
            expr = line.expression_ids.filtered(lambda e: e.label == label)[:1]
            if expr:
                return eval_expression(expr, date_from, date_to)
            if label == 'balance' and line.aggregation_formula:
                return eval_aggregation_formula(line.aggregation_formula, date_from, date_to)
            return 0.0

        def eval_aggregation_formula(formula, date_from, date_to):
            if not formula:
                return 0.0
            def repl(match):
                return str(get_expr_value(match.group(1), match.group(2), date_from, date_to))
            safe = AGG_TOKEN_RE.sub(repl, formula)
            if not re.fullmatch(r'[0-9+\-*/().\s]+', safe):
                return 0.0
            try:
                return float(eval(safe, {'__builtins__': {}}, {}))  # noqa: S307
            except Exception:
                return 0.0

        def eval_expression(expr, date_from, date_to):
            cache_key = (expr.id, date_from, date_to, 'full')
            if cache_key in expression_cache:
                return expression_cache[cache_key]
            if expr.engine == 'domain':
                value = eval_domain_expression(expr, date_from, date_to)
            elif expr.engine == 'aggregation':
                if expr.subformula == 'cross_report' and 'NEP' in (expr.formula or ''):
                    value = self._abr_current_year_earnings(options, date_from, date_to, company)
                else:
                    value = eval_aggregation_formula(expr.formula, date_from, date_to)
            else:
                value = 0.0
            expression_cache[cache_key] = value
            return value

        def line_balance_value(report_line, date_from, date_to):
            balance_expr = report_line.expression_ids.filtered(lambda e: e.label == 'balance')[:1]
            if balance_expr:
                return eval_expression(balance_expr, date_from, date_to)
            if report_line.aggregation_formula:
                return eval_aggregation_formula(report_line.aggregation_formula, date_from, date_to)
            return 0.0

        for report_line in self.line_ids:
            vals = {}
            for spec in period_specs:
                vals[spec['key_prefix'] + 'balance'] = line_balance_value(
                    report_line, spec['date_from'], spec['date_to'],
                )
            line_values[report_line.id] = vals

        lines = []

        def is_unfolded(line_id):
            return unfold_all or line_id in unfolded

        def line_is_zero(report_line, vals):
            if not options.get('hide_zero_lines') and not report_line.hide_if_zero:
                return False
            col_vals = [vals.get(c['key'], 0.0) for c in options['columns']]
            return all(float_is_zero(v, precision_rounding=currency.rounding) for v in col_vals)

        def append_account_children(report_line, parent_line_id, level, side):
            balance_expr = report_line.expression_ids.filtered(lambda e: e.engine == 'domain' and e.label == 'balance')[:1]
            if not balance_expr:
                balance_expr = report_line.expression_ids.filtered(lambda e: e.engine == 'domain')[:1]
            if not balance_expr:
                return
            try:
                ml_domain = ast.literal_eval(balance_expr.formula)
            except Exception:
                return
            scope = balance_expr.date_scope or 'strict_range'
            if scope == 'strict_range' and not options.get('filter_date_range'):
                scope = 'from_beginning'
            d_to = fields.Date.to_date(options['date_to'])
            d_from = fields.Date.to_date(options['date_from'])
            aml_domain = self._abr_base_aml_domain(options)
            aml_domain = [d for d in aml_domain if not (isinstance(d, tuple) and d[0] == 'date')]
            aml_domain += self._abr_scope_date_domain(scope, d_from, d_to, company)
            aml_domain += ml_domain
            balances = self._abr_read_group_balances(aml_domain)
            sign = -1.0 if balance_expr.subformula == '-sum' else 1.0
            for account in self.env['account.account'].browse(balances.keys()).sorted(key=lambda a: (a.code or '', a.id)):
                col_vals = {'balance': sign * balances[account.id]['balance']}
                skip = options.get('hide_zero_lines') and float_is_zero(col_vals['balance'], precision_rounding=currency.rounding)
                for idx, period in enumerate(options.get('comparison_periods') or []):
                    p_domain = self._abr_base_aml_domain(options)
                    p_domain = [d for d in p_domain if not (isinstance(d, tuple) and d[0] == 'date')]
                    p_domain += [
                        ('date', '<=', fields.Date.to_date(period['date_to'])),
                        ('account_id', '=', account.id),
                    ] + list(ml_domain)
                    val = sign * self._abr_aggregate_balance(p_domain)
                    col_vals['comp_%s_balance' % idx] = val
                    if not float_is_zero(val, precision_rounding=currency.rounding):
                        skip = False
                if skip:
                    continue
                lines.append({
                    'id': 'report_line_%s_account_%s' % (report_line.id, account.id),
                    'parent_id': parent_line_id,
                    'name': account.display_name,
                    'code': account.code,
                    'level': level,
                    'unfoldable': False,
                    'unfolded': False,
                    'caret': True,
                    'account_id': account.id,
                    'side': side,
                    'columns': self._abr_columns_from_vals(options, col_vals),
                    'class': '',
                })

        def process_line(report_line, level=None):
            level = report_line.hierarchy_level if level is None else level
            line_id = 'report_line_%s' % report_line.id
            vals = line_values.get(report_line.id, {})
            if report_line.hide_if_zero and float_is_zero(vals.get('balance', 0.0), precision_rounding=currency.rounding):
                return
            if line_is_zero(report_line, vals) and not report_line.children_ids:
                return

            has_children = bool(report_line.children_ids) or bool(report_line.groupby)
            unfolded_flag = has_children and (is_unfolded(line_id) or (not report_line.foldable and has_children))
            if unfold_all and has_children:
                unfolded_flag = True
            side = report_line.horizontal_split_side or 'left'
            lines.append({
                'id': line_id,
                'parent_id': 'report_line_%s' % report_line.parent_id.id if report_line.parent_id else None,
                'name': report_line.name,
                'code': report_line.code,
                'level': level,
                'unfoldable': bool(has_children and report_line.foldable) or bool(report_line.groupby),
                'unfolded': unfolded_flag,
                'caret': False,
                'side': side,
                'columns': self._abr_columns_from_vals(options, vals),
                'class': 'o_abr_section' if level <= 1 else ('o_abr_group' if has_children else ''),
            })
            if unfolded_flag or (has_children and not report_line.foldable):
                for child in report_line.children_ids.sorted('sequence'):
                    process_line(child)
                if report_line.groupby and (unfolded_flag or unfold_all or not report_line.foldable):
                    append_account_children(report_line, line_id, level + 1, side)

        for root in self.line_ids.filtered(lambda l: not l.parent_id).sorted('sequence'):
            process_line(root)

        search = (options.get('search_value') or '').strip().lower()
        if search:
            lines = [l for l in lines if search in (l.get('name') or '').lower() or search in (l.get('code') or '').lower()]
        return lines

    def _abr_columns_from_vals(self, options, vals):
        return [{
            'name': col['name'],
            'key': col['key'],
            'no_format': vals.get(col['key'], 0.0),
        } for col in options['columns']]

    def _abr_scope_date_domain(self, scope, date_from, date_to, company):
        if scope == 'from_fiscalyear':
            fy = company.compute_fiscalyear_dates(date_to)
            return [('date', '>=', fy['date_from']), ('date', '<=', date_to)]
        if scope == 'strict_range':
            return [('date', '>=', date_from), ('date', '<=', date_to)]
        if scope == 'to_beginning_of_period':
            return [('date', '<', date_from)]
        if scope == 'to_beginning_of_fiscalyear':
            fy = company.compute_fiscalyear_dates(date_to)
            return [('date', '<', fy['date_from'])]
        return [('date', '<=', date_to)]

    def _abr_current_year_earnings(self, options, date_from, date_to, company):
        d_to = fields.Date.to_date(date_to)
        fy = company.compute_fiscalyear_dates(d_to)
        domain = self._abr_base_aml_domain(options)
        domain = [d for d in domain if not (isinstance(d, tuple) and d[0] == 'date')]
        domain += [
            ('date', '>=', fy['date_from']),
            ('date', '<=', d_to),
            ('account_id.account_type', 'in', (
                'income', 'income_other', 'expense_direct_cost', 'expense', 'expense_depreciation',
            )),
        ]
        return -self._abr_aggregate_balance(domain)
