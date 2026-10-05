# -*- coding: utf-8 -*-
import ast
import json
import re
from dateutil.relativedelta import relativedelta

from odoo import fields, models, _
from odoo.tools import float_is_zero


AGG_TOKEN_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)')


class AccountReport(models.Model):
    _inherit = 'account.report'

    abr_handler = fields.Selection(
        selection=[
            ('balance_sheet', 'Balance Sheet'),
            ('trial_balance', 'Trial Balance'),
        ],
        string='Community Report Handler',
        help='Original Community computation handler used by account_balance_reports.',
    )

    # -------------------------------------------------------------------------
    # Public RPC API used by the OWL client action
    # -------------------------------------------------------------------------

    def abr_get_report_payload(self, options=None):
        """Return options + lines for the interactive report UI."""
        self.ensure_one()
        options = self.abr_get_options(options or {})
        if self.abr_handler == 'trial_balance':
            lines = self.env['account.report.trial.balance'].abr_get_lines(self, options)
        else:
            lines = self.abr_get_balance_sheet_lines(options)
        return {
            'options': options,
            'lines': lines,
            'report_name': self.name,
            'handler': self.abr_handler or 'balance_sheet',
        }

    def abr_open_journal_items(self, options, line_id):
        self.ensure_one()
        options = self.abr_get_options(options or {})
        domain = self._abr_base_aml_domain(options)
        parsed = self._abr_parse_line_id(line_id)
        if parsed.get('account_id'):
            domain.append(('account_id', '=', parsed['account_id']))
        elif parsed.get('account_group_id'):
            domain.append(('account_id.group_id', 'child_of', parsed['account_group_id']))
        elif parsed.get('report_line_id'):
            report_line = self.env['account.report.line'].browse(parsed['report_line_id'])
            account_domain = self._abr_account_domain_from_line(report_line)
            if account_domain:
                accounts = self.env['account.account'].search(account_domain)
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
        options = self.abr_get_options(options or {})
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
        options = self.abr_get_options(options or {})
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
        previous_options = previous_options or {}
        company = self.env.company
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

        selected_journal_ids = previous_options.get('journal_ids') or []
        journals = self.env['account.journal'].search([
            ('company_id', 'child_of', company.id),
        ])

        companies = self.env.companies if self.filter_multi_company == 'selector' else company
        selected_company_ids = previous_options.get('company_ids') or companies.ids

        hierarchy = previous_options.get('hierarchy')
        if hierarchy is None:
            hierarchy = self.filter_hierarchy == 'by_default'

        hide_zero = previous_options.get('hide_zero_lines')
        if hide_zero is None:
            hide_zero = self.filter_hide_0_lines == 'by_default'

        unfold_all = bool(previous_options.get('unfold_all', False))
        unfolded_lines = set(previous_options.get('unfolded_lines') or [])
        if unfold_all:
            unfolded_lines = set()  # resolved after lines are known; flag kept

        options = {
            'report_id': self.id,
            'handler': self.abr_handler or 'balance_sheet',
            'date_filter': date_filter,
            'date_from': fields.Date.to_string(date_from),
            'date_to': fields.Date.to_string(date_to),
            'filter_date_range': bool(self.filter_date_range),
            'all_entries': bool(previous_options.get('all_entries', False)),
            'journal_ids': selected_journal_ids,
            'available_journals': [{'id': j.id, 'name': j.display_name} for j in journals],
            'company_ids': selected_company_ids,
            'available_companies': [{'id': c.id, 'name': c.name} for c in self.env['res.company'].browse(companies.ids)],
            'multi_company': self.filter_multi_company == 'selector',
            'hierarchy': bool(hierarchy),
            'filter_hierarchy': self.filter_hierarchy or 'optional',
            'hide_zero_lines': bool(hide_zero),
            'filter_hide_0_lines': self.filter_hide_0_lines or 'optional',
            'unfold_all': unfold_all,
            'unfolded_lines': list(unfolded_lines),
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
            'currency_position': company.currency_id.position,
            'decimal_places': company.currency_id.decimal_places,
        }

        # Analytic filter when analytic accounting is available
        if 'analytic.account' in self.env and previous_options.get('analytic_account_ids') is not None:
            options['analytic_account_ids'] = previous_options.get('analytic_account_ids') or []
            options['filter_analytic'] = True
        elif self.filter_analytic and 'analytic.account' in self.env:
            options['analytic_account_ids'] = previous_options.get('analytic_account_ids') or []
            options['filter_analytic'] = True
            options['available_analytic_accounts'] = [
                {'id': a.id, 'name': a.display_name}
                for a in self.env['analytic.account'].search([], limit=200)
            ]
        else:
            options['filter_analytic'] = False
            options['analytic_account_ids'] = []

        options['columns'] = self._abr_build_columns(options)
        return options

    def _abr_dates_from_filter(self, date_filter, today, company):
        if date_filter == 'today':
            return today, today
        if date_filter == 'this_month':
            start = today.replace(day=1)
            end = start + relativedelta(months=1, days=-1)
            return start, end
        if date_filter == 'previous_month':
            end = today.replace(day=1) - relativedelta(days=1)
            start = end.replace(day=1)
            return start, end
        if date_filter == 'this_quarter':
            quarter = (today.month - 1) // 3
            start = today.replace(month=quarter * 3 + 1, day=1)
            end = start + relativedelta(months=3, days=-1)
            return start, end
        if date_filter == 'previous_quarter':
            this_q_start_month = ((today.month - 1) // 3) * 3 + 1
            this_q_start = today.replace(month=this_q_start_month, day=1)
            end = this_q_start - relativedelta(days=1)
            start = end.replace(month=((end.month - 1) // 3) * 3 + 1, day=1)
            return start, end
        if date_filter == 'this_year':
            fy = company.compute_fiscalyear_dates(today)
            return fy['date_from'], fy['date_to']
        if date_filter == 'previous_year':
            fy = company.compute_fiscalyear_dates(today)
            prev_day = fy['date_from'] - relativedelta(days=1)
            prev_fy = company.compute_fiscalyear_dates(prev_day)
            return prev_fy['date_from'], prev_fy['date_to']
        # fallback month
        start = today.replace(day=1)
        end = start + relativedelta(months=1, days=-1)
        return start, end

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

    def _abr_build_columns(self, options):
        columns = []
        if options.get('handler') == 'trial_balance':
            columns.append({'name': _('Initial Debit'), 'key': 'initial_debit', 'group': _('Initial Balance')})
            columns.append({'name': _('Initial Credit'), 'key': 'initial_credit', 'group': _('Initial Balance')})
            columns.append({'name': _('Debit'), 'key': 'debit', 'group': _('Period')})
            columns.append({'name': _('Credit'), 'key': 'credit', 'group': _('Period')})
            for idx, period in enumerate(options.get('comparison_periods') or []):
                columns.append({
                    'name': _('Debit'),
                    'key': 'comp_%s_debit' % idx,
                    'group': period['string'],
                })
                columns.append({
                    'name': _('Credit'),
                    'key': 'comp_%s_credit' % idx,
                    'group': period['string'],
                })
            columns.append({'name': _('End Debit'), 'key': 'end_debit', 'group': _('End Balance')})
            columns.append({'name': _('End Credit'), 'key': 'end_credit', 'group': _('End Balance')})
            return columns

        columns.append({'name': _('Balance'), 'key': 'balance', 'group': options['date_to']})
        for idx, period in enumerate(options.get('comparison_periods') or []):
            columns.append({
                'name': _('Balance'),
                'key': 'comp_%s_balance' % idx,
                'group': period['string'],
            })
        return columns

    # -------------------------------------------------------------------------
    # Domains / balances helpers
    # -------------------------------------------------------------------------

    def _abr_company_ids(self, options):
        ids = options.get('company_ids') or [self.env.company.id]
        return self.env['res.company'].browse(ids).ids

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
        if options.get('analytic_account_ids'):
            # analytic_distribution is JSON; use analytic line filter when possible
            domain.append(('analytic_distribution', '!=', False))
        date_to = date_to or options.get('date_to')
        date_from = date_from or options.get('date_from')
        if date_to:
            domain.append(('date', '<=', date_to))
        if date_from and strict_range:
            domain.append(('date', '>=', date_from))
        elif date_from and not strict_range and date_from:
            # used for "before period" by callers that pass only date_from as cutoff
            pass
        return domain

    def _abr_read_group_balances(self, domain):
        groups = self.env['account.move.line']._read_group(
            domain,
            groupby=['account_id'],
            aggregates=['debit:sum', 'credit:sum', 'balance:sum'],
        )
        result = {}
        for account, debit, credit, balance in groups:
            if not account:
                continue
            result[account.id] = {
                'debit': debit or 0.0,
                'credit': credit or 0.0,
                'balance': balance or 0.0,
            }
        return result

    def _abr_account_company_domain(self, options):
        company_ids = self._abr_company_ids(options)
        return [
            '|',
            ('company_ids', 'parent_of', company_ids),
            ('company_ids', 'child_of', company_ids),
        ]

    def _abr_split_debit_credit(self, balance, currency):
        if currency.compare_amounts(balance, 0.0) > 0:
            return balance, 0.0
        if currency.compare_amounts(balance, 0.0) < 0:
            return 0.0, abs(balance)
        return 0.0, 0.0

    def _abr_parse_line_id(self, line_id):
        """line_id format examples:
        - report_line_42
        - report_line_42_account_15
        - account_15
        - group_8
        """
        result = {}
        if not line_id:
            return result
        parts = str(line_id).split('_')
        i = 0
        while i < len(parts):
            key = parts[i]
            if key in ('report', 'line') and i + 2 < len(parts) and parts[i] == 'report' and parts[i + 1] == 'line':
                result['report_line_id'] = int(parts[i + 2])
                i += 3
            elif key == 'account' and i + 1 < len(parts):
                result['account_id'] = int(parts[i + 1])
                i += 2
            elif key == 'group' and i + 1 < len(parts):
                result['account_group_id'] = int(parts[i + 1])
                i += 2
            else:
                i += 1
        return result

    def _abr_account_domain_from_line(self, report_line):
        """Extract account domain from a report line's domain expressions."""
        for expr in report_line.expression_ids.filtered(lambda e: e.engine == 'domain'):
            try:
                formula = ast.literal_eval(expr.formula)
            except Exception:
                continue
            # Convert move-line style domain to account domain when possible
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
                return self._abr_account_company_domain({'company_ids': self.env.company.ids}) + account_domain
        # recurse children domains as OR is too broad; return empty
        return []

    # -------------------------------------------------------------------------
    # Balance Sheet computation
    # -------------------------------------------------------------------------

    def abr_get_balance_sheet_lines(self, options):
        self.ensure_one()
        currency = self.env.company.currency_id
        unfolded = set(options.get('unfolded_lines') or [])
        unfold_all = options.get('unfold_all')

        # Period column groups: main + comparisons
        period_specs = [{
            'key_prefix': '',
            'date_from': options['date_from'],
            'date_to': options['date_to'],
        }]
        for idx, period in enumerate(options.get('comparison_periods') or []):
            period_specs.append({
                'key_prefix': 'comp_%s_' % idx,
                'date_from': period['date_from'],
                'date_to': period['date_to'],
            })

        expression_cache = {}  # (expr_id, date_from, date_to) -> value
        line_values = {}  # report_line.id -> {balance keys}

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
            # date scope
            scope = expr.date_scope or 'strict_range'
            # Balance Sheet is point-in-time: cumulative balances up to date_to
            if options.get('handler') == 'balance_sheet' and scope == 'strict_range' and not options.get('filter_date_range'):
                scope = 'from_beginning'
            d_from = fields.Date.to_date(date_from)
            d_to = fields.Date.to_date(date_to)
            company = self.env.company
            if scope == 'from_fiscalyear':
                fy = company.compute_fiscalyear_dates(d_to)
                aml_domain += [('date', '>=', fy['date_from']), ('date', '<=', d_to)]
            elif scope == 'strict_range':
                aml_domain += [('date', '>=', d_from), ('date', '<=', d_to)]
            elif scope == 'to_beginning_of_period':
                aml_domain += [('date', '<', d_from)]
            elif scope == 'to_beginning_of_fiscalyear':
                fy = company.compute_fiscalyear_dates(d_to)
                aml_domain += [('date', '<', fy['date_from'])]
            else:  # from_beginning
                aml_domain += [('date', '<=', d_to)]
            aml_domain += ml_domain
            groups = self.env['account.move.line']._read_group(
                aml_domain, groupby=[], aggregates=['balance:sum'],
            )
            balance = groups[0][0] if groups else 0.0
            balance = balance or 0.0
            sub = expr.subformula or 'sum'
            if sub == '-sum':
                balance = -balance
            elif sub == 'sum':
                pass
            expression_cache[cache_key] = balance
            return balance

        def get_expr_value(line_code, label, date_from, date_to):
            line = self.line_ids.filtered(lambda l: l.code == line_code)[:1]
            if not line:
                return 0.0
            expr = line.expression_ids.filtered(lambda e: e.label == label)[:1]
            if not expr:
                return 0.0
            return eval_expression(expr, date_from, date_to)

        def eval_aggregation_formula(formula, date_from, date_to):
            if not formula:
                return 0.0
            # Replace CODE.label tokens with values
            def repl(match):
                code, label = match.group(1), match.group(2)
                return str(get_expr_value(code, label, date_from, date_to))
            safe = AGG_TOKEN_RE.sub(repl, formula)
            # Only allow numbers and +-*/
            if not re.fullmatch(r'[0-9+\-*/().\s]+', safe):
                return 0.0
            try:
                return float(eval(safe, {'__builtins__': {}}, {}))  # noqa: S307 - sanitized
            except Exception:
                return 0.0

        def eval_expression(expr, date_from, date_to):
            cache_key = (expr.id, date_from, date_to, 'full', tuple(options.get('journal_ids') or ()), tuple(options.get('company_ids') or ()))
            if cache_key in expression_cache:
                return expression_cache[cache_key]
            value = 0.0
            if expr.engine == 'domain':
                value = eval_domain_expression(expr, date_from, date_to)
            elif expr.engine == 'aggregation':
                if expr.subformula == 'cross_report':
                    # For Community BS we map NEP.balance to P&L of income/expense
                    if 'NEP' in (expr.formula or ''):
                        value = self._abr_current_year_earnings(options, date_from, date_to)
                    else:
                        value = eval_aggregation_formula(expr.formula, date_from, date_to)
                else:
                    value = eval_aggregation_formula(expr.formula, date_from, date_to)
            expression_cache[cache_key] = value
            return value

        # Evaluate all expressions for all periods, storing per line
        for report_line in self.line_ids:
            vals = {}
            for spec in period_specs:
                prefix = spec['key_prefix']
                balance_expr = report_line.expression_ids.filtered(lambda e: e.label == 'balance')[:1]
                if balance_expr:
                    vals[prefix + 'balance'] = eval_expression(balance_expr, spec['date_from'], spec['date_to'])
                else:
                    vals[prefix + 'balance'] = 0.0
            line_values[report_line.id] = vals

        lines = []

        def is_unfolded(line_id):
            return unfold_all or line_id in unfolded

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
            if options.get('handler') == 'balance_sheet' and scope == 'strict_range' and not options.get('filter_date_range'):
                scope = 'from_beginning'
            d_to = fields.Date.to_date(options['date_to'])
            d_from = fields.Date.to_date(options['date_from'])
            aml_domain = self._abr_base_aml_domain(options)
            aml_domain = [d for d in aml_domain if not (isinstance(d, tuple) and d[0] == 'date')]
            if scope == 'from_fiscalyear':
                fy = self.env.company.compute_fiscalyear_dates(d_to)
                aml_domain += [('date', '>=', fy['date_from']), ('date', '<=', d_to)]
            elif scope == 'strict_range':
                aml_domain += [('date', '>=', d_from), ('date', '<=', d_to)]
            else:
                aml_domain += [('date', '<=', d_to)]
            aml_domain += ml_domain
            balances = self._abr_read_group_balances(aml_domain)
            Account = self.env['account.account']
            sign = -1.0 if (balance_expr.subformula == '-sum') else 1.0
            for account in Account.browse(balances.keys()).sorted(key=lambda a: (a.code or '', a.id)):
                main_balance = sign * balances[account.id]['balance']
                skip = options.get('hide_zero_lines') and float_is_zero(
                    main_balance, precision_rounding=currency.rounding
                )
                col_vals = {'balance': main_balance}
                for idx, period in enumerate(options.get('comparison_periods') or []):
                    p_domain = self._abr_base_aml_domain(options)
                    p_domain = [d for d in p_domain if not (isinstance(d, tuple) and d[0] == 'date')]
                    p_domain += [('date', '<=', period['date_to']), ('account_id', '=', account.id)] + list(ml_domain)
                    p_bal = self._abr_read_group_balances(p_domain)
                    val = sign * (p_bal.get(account.id, {}).get('balance', 0.0))
                    col_vals['comp_%s_balance' % idx] = val
                    if not float_is_zero(val, precision_rounding=currency.rounding):
                        skip = False
                if skip and options.get('hide_zero_lines'):
                    continue
                columns = [{
                    'name': col['name'],
                    'key': col['key'],
                    'no_format': col_vals.get(col['key'], 0.0),
                } for col in options['columns']]
                acc_line_id = 'report_line_%s_account_%s' % (report_line.id, account.id)
                lines.append({
                    'id': acc_line_id,
                    'parent_id': parent_line_id,
                    'name': account.display_name,
                    'code': account.code,
                    'level': level,
                    'unfoldable': False,
                    'unfolded': False,
                    'caret': True,
                    'account_id': account.id,
                    'side': side,
                    'columns': columns,
                    'class': '',
                })

        root_lines = self.line_ids.filtered(lambda l: not l.parent_id).sorted('sequence')

        def process_line(report_line, level=0):
            line_id = 'report_line_%s' % report_line.id
            vals = line_values.get(report_line.id, {})
            if report_line.hide_if_zero and float_is_zero(vals.get('balance', 0.0), precision_rounding=currency.rounding):
                return
            if options.get('hide_zero_lines') and float_is_zero(vals.get('balance', 0.0), precision_rounding=currency.rounding):
                # show section headers anyway if they have children with values - keep simple: hide
                if report_line.expression_ids.filtered(lambda e: e.engine == 'domain'):
                    pass
            columns = []
            for col in options['columns']:
                columns.append({
                    'name': col['name'],
                    'key': col['key'],
                    'no_format': vals.get(col['key'], 0.0),
                })
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
                'columns': columns,
                'class': 'o_abr_section' if level == 0 else ('o_abr_group' if has_children else ''),
            })
            if unfolded_flag or (has_children and not report_line.foldable):
                for child in report_line.children_ids.sorted('sequence'):
                    process_line(child, level=level + 1)
                if report_line.groupby and (unfolded_flag or unfold_all or not report_line.foldable):
                    append_account_children(report_line, line_id, level + 1, side)
            elif report_line.groupby and unfolded_flag:
                append_account_children(report_line, line_id, level + 1, side)

        for root in root_lines:
            process_line(root, level=0)

        # Apply search filter
        search = (options.get('search_value') or '').strip().lower()
        if search:
            lines = [l for l in lines if search in (l.get('name') or '').lower() or search in (l.get('code') or '').lower()]

        return lines

    def _abr_current_year_earnings(self, options, date_from, date_to):
        """Net earnings from fiscal year start to date_to (equity sign)."""
        d_to = fields.Date.to_date(date_to)
        fy = self.env.company.compute_fiscalyear_dates(d_to)
        domain = self._abr_base_aml_domain(options)
        domain = [d for d in domain if not (isinstance(d, tuple) and d[0] == 'date')]
        domain += [
            ('date', '>=', fy['date_from']),
            ('date', '<=', d_to),
            ('account_id.account_type', 'in', (
                'income', 'income_other', 'expense_direct_cost', 'expense', 'expense_depreciation',
            )),
        ]
        groups = self.env['account.move.line']._read_group(domain, groupby=[], aggregates=['balance:sum'])
        balance = groups[0][0] if groups else 0.0
        return -(balance or 0.0)
