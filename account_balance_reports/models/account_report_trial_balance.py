# -*- coding: utf-8 -*-
from collections import defaultdict

from odoo import api, fields, models, _
from odoo.tools import float_is_zero, float_round


class AccountReportTrialBalance(models.AbstractModel):
    _name = 'account.report.trial.balance'
    _description = 'Trial Balance Report Handler'

    @api.model
    def abr_get_lines(self, report, options):
        company = report._abr_get_main_company(options)
        currency = company.currency_id
        date_from = fields.Date.to_date(options['date_from'])
        date_to = fields.Date.to_date(options['date_to'])

        initial_domain = report._abr_base_aml_domain(options)
        initial_domain = [d for d in initial_domain if not (isinstance(d, tuple) and d[0] == 'date')]
        initial_domain.append(('date', '<', date_from))

        period_domain = report._abr_base_aml_domain(options, date_from=date_from, date_to=date_to, strict_range=True)
        end_domain = report._abr_base_aml_domain(options)
        end_domain = [d for d in end_domain if not (isinstance(d, tuple) and d[0] == 'date')]
        end_domain.append(('date', '<=', date_to))

        initial_map = report._abr_read_group_balances(initial_domain)
        period_map = report._abr_read_group_balances(period_domain)
        end_map = report._abr_read_group_balances(end_domain)

        comparison_maps = []
        for period in options.get('comparison_periods') or []:
            p_from = fields.Date.to_date(period['date_from'])
            p_to = fields.Date.to_date(period['date_to'])
            p_domain = report._abr_base_aml_domain(options, date_from=p_from, date_to=p_to, strict_range=True)
            comparison_maps.append(report._abr_read_group_balances(p_domain))

        account_ids = set(initial_map) | set(period_map) | set(end_map)
        for cmap in comparison_maps:
            account_ids |= set(cmap)

        accounts = self.env['account.account'].browse(list(account_ids)).sorted(
            key=lambda a: (a.code or '', a.id),
        )

        unfolded = set(options.get('unfolded_lines') or [])
        unfold_all = options.get('unfold_all')
        search = (options.get('search_value') or '').strip().lower()

        account_rows = []
        totals = defaultdict(float)

        for account in accounts:
            init_bal = initial_map.get(account.id, {}).get('balance', 0.0)
            end_bal = end_map.get(account.id, {}).get('balance', 0.0)
            init_debit, init_credit = report._abr_split_debit_credit(init_bal, currency)
            end_debit, end_credit = report._abr_split_debit_credit(end_bal, currency)
            period_debit = period_map.get(account.id, {}).get('debit', 0.0)
            period_credit = period_map.get(account.id, {}).get('credit', 0.0)

            col_vals = {
                'initial_debit': init_debit,
                'initial_credit': init_credit,
                'debit': period_debit,
                'credit': period_credit,
                'end_debit': end_debit,
                'end_credit': end_credit,
            }
            for idx, cmap in enumerate(comparison_maps):
                comp_bal = cmap.get(account.id, {}).get('balance', 0.0)
                comp_debit, comp_credit = report._abr_split_debit_credit(comp_bal, currency)
                col_vals['comp_%s_debit' % idx] = comp_debit
                col_vals['comp_%s_credit' % idx] = comp_credit

            if options.get('hide_zero_lines'):
                if all(float_is_zero(col_vals.get(c['key'], 0.0), precision_rounding=currency.rounding)
                       for c in options['columns']):
                    continue

            if search and search not in (account.display_name or '').lower() and search not in (account.code or '').lower():
                continue

            columns = report._abr_columns_from_vals(options, col_vals)
            for col in columns:
                totals[col['key']] += col['no_format']

            account_rows.append({
                'id': 'account_%s' % account.id,
                'parent_id': 'group_%s' % account.group_id.id if options.get('hierarchy') and account.group_id else None,
                'name': account.display_name,
                'code': account.code,
                'level': 2 if options.get('hierarchy') else 0,
                'unfoldable': False,
                'unfolded': False,
                'caret': True,
                'account_id': account.id,
                'account_group_id': account.group_id.id if account.group_id else False,
                'side': None,
                'columns': columns,
                'class': '',
            })

        if options.get('hierarchy'):
            lines = self._apply_hierarchy(options, account_rows, unfolded, unfold_all)
        else:
            lines = account_rows

        total_columns = [{
            'name': col['name'],
            'key': col['key'],
            'no_format': float_round(totals[col['key']], precision_rounding=currency.rounding),
        } for col in options['columns']]
        lines.append({
            'id': 'total',
            'parent_id': None,
            'name': _('Total'),
            'code': '',
            'level': 0,
            'unfoldable': False,
            'unfolded': False,
            'caret': False,
            'side': None,
            'columns': total_columns,
            'class': 'o_abr_total',
        })
        return lines

    @api.model
    def _apply_hierarchy(self, options, account_rows, unfolded, unfold_all):
        AccountGroup = self.env['account.group']
        groups_needed = {}
        for row in account_rows:
            group = AccountGroup.browse(row['account_group_id']) if row.get('account_group_id') else AccountGroup
            while group:
                groups_needed[group.id] = group
                group = group.parent_id

        if not groups_needed:
            return account_rows

        def depth(group):
            d, p = 0, group.parent_id
            while p:
                d += 1
                p = p.parent_id
            return d

        group_lines = {}
        for group in sorted(groups_needed.values(), key=lambda g: (g.code_prefix_start or '', g.id)):
            line_id = 'group_%s' % group.id
            group_lines[group.id] = {
                'id': line_id,
                'parent_id': 'group_%s' % group.parent_id.id if group.parent_id and group.parent_id.id in groups_needed else None,
                'name': group.display_name,
                'code': group.code_prefix_start or '',
                'level': depth(group) + 1,
                'unfoldable': True,
                'unfolded': unfold_all or line_id in unfolded,
                'caret': True,
                'account_group_id': group.id,
                'side': None,
                'columns': [{'name': c['name'], 'key': c['key'], 'no_format': 0.0} for c in options['columns']],
                'class': 'o_abr_group',
                '_children': [],
            }

        orphans = []
        for row in account_rows:
            gid = row.get('account_group_id')
            if gid and gid in group_lines:
                parent = group_lines[gid]
                row['parent_id'] = parent['id']
                row['level'] = parent['level'] + 1
                parent['_children'].append(row)
            else:
                row['parent_id'] = None
                orphans.append(row)

        for group in groups_needed.values():
            if group.parent_id and group.parent_id.id in group_lines:
                parent_gl = group_lines[group.parent_id.id]
                child_gl = group_lines[group.id]
                if child_gl not in parent_gl['_children']:
                    parent_gl['_children'].insert(0, child_gl)

        for group in sorted(groups_needed.values(), key=lambda g: -depth(g)):
            gl = group_lines[group.id]
            totals_cols = [0.0] * len(options['columns'])
            for child in gl['_children']:
                for i, col in enumerate(child['columns']):
                    totals_cols[i] += col['no_format']
            for i, col in enumerate(gl['columns']):
                col['no_format'] = totals_cols[i]

        lines = []

        def emit(node):
            lines.append({k: v for k, v in node.items() if k != '_children'})
            if node.get('unfoldable') and not node.get('unfolded'):
                return
            for child in node.get('_children', []):
                if child.get('unfoldable') and '_children' in child:
                    emit(child)
                else:
                    lines.append({k: v for k, v in child.items() if k != '_children'})

        roots = sorted([gl for gl in group_lines.values() if not gl['parent_id']], key=lambda r: (r.get('code') or '', r['name']))
        for root in roots:
            emit(root)
        lines.extend(sorted(orphans, key=lambda r: (r.get('code') or '', r['name'])))
        return lines
