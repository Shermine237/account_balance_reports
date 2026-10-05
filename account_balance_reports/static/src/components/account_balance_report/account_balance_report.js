/** @odoo-module **/

import { _t } from "@web/core/l10n/translation";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

export class AccountBalanceReportAction extends Component {
    static template = "account_balance_reports.AccountBalanceReportAction";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.state = useState({
            loading: true,
            reportName: "",
            handler: "balance_sheet",
            options: {},
            lines: [],
            warnings: [],
            showJournalDropdown: false,
            showAnalyticDropdown: false,
            showCompanyDropdown: false,
        });
        onWillStart(async () => {
            await this.reload();
        });
    }

    get reportId() {
        const ctx = this.props.action.context || {};
        return ctx.report_id || ctx.active_id;
    }

    get dateFilters() {
        return [
            { value: "today", label: _t("Today") },
            { value: "this_month", label: _t("This Month") },
            { value: "previous_month", label: _t("Last Month") },
            { value: "this_quarter", label: _t("This Quarter") },
            { value: "previous_quarter", label: _t("Last Quarter") },
            { value: "this_year", label: _t("This Year") },
            { value: "previous_year", label: _t("Last Year") },
        ];
    }

    get columnGroups() {
        const cols = this.state.options.columns || [];
        const groups = [];
        let current = null;
        for (const col of cols) {
            const g = col.group || "";
            if (!current || current.name !== g) {
                current = { name: g, columns: [] };
                groups.push(current);
            }
            current.columns.push(col);
        }
        return groups;
    }

    get leftLines() {
        if (!this.state.options.horizontal_split) {
            return this.visibleLines;
        }
        return this.visibleLines.filter((l) => l.side !== "right");
    }

    get rightLines() {
        if (!this.state.options.horizontal_split) {
            return [];
        }
        return this.visibleLines.filter((l) => l.side === "right");
    }

    get visibleLines() {
        return this.state.lines || [];
    }

    get journalLabel() {
        const ids = this.state.options.journal_ids || [];
        if (!ids.length) {
            return _t("All Journals");
        }
        const names = (this.state.options.available_journals || [])
            .filter((j) => ids.includes(j.id))
            .map((j) => j.name);
        return names.length <= 2 ? names.join(", ") : _t("%s journals", names.length);
    }

    get postedLabel() {
        return this.state.options.all_entries ? _t("All Entries") : _t("Posted Entries");
    }

    get currencyLabel() {
        return _t("In %s", this.state.options.currency_name || this.state.options.currency_symbol || "");
    }

    async reload() {
        this.state.loading = true;
        try {
            const previous = this.state.options?.report_id ? this._optionsPayload() : {};
            const payload = await this.orm.call("account.report", "abr_get_report_payload", [
                [this.reportId],
                previous,
            ]);
            this.state.options = payload.options;
            this.state.lines = payload.lines;
            this.state.reportName = payload.report_name;
            this.state.handler = payload.handler;
            this.state.warnings = payload.warnings || [];
        } finally {
            this.state.loading = false;
        }
    }

    _optionsPayload() {
        const o = this.state.options;
        return {
            date_filter: o.date_filter,
            date_from: o.date_from,
            date_to: o.date_to,
            all_entries: o.all_entries,
            journal_ids: o.journal_ids,
            company_ids: o.company_ids,
            hierarchy: o.hierarchy,
            hide_zero_lines: o.hide_zero_lines,
            unfold_all: o.unfold_all,
            unfolded_lines: o.unfolded_lines,
            comparison: o.comparison,
            search_value: o.search_value,
            analytic_account_ids: o.analytic_account_ids,
        };
    }

    async applyOptions(patch) {
        this.state.options = { ...this.state.options, ...patch };
        await this.reload();
    }

    onDateFilterChange(ev) {
        this.applyOptions({ date_filter: ev.target.value });
    }

    onDateFromChange(ev) {
        this.applyOptions({ date_from: ev.target.value, date_filter: "custom" });
    }

    onDateToChange(ev) {
        this.applyOptions({ date_to: ev.target.value, date_filter: "custom" });
    }

    toggleAllEntries() {
        this.applyOptions({ all_entries: !this.state.options.all_entries });
    }

    onHierarchyChange(ev) {
        this.applyOptions({ hierarchy: ev.target.checked });
    }

    onHideZeroChange(ev) {
        this.applyOptions({ hide_zero_lines: ev.target.checked });
    }

    onUnfoldAllChange(ev) {
        this.applyOptions({ unfold_all: ev.target.checked, unfolded_lines: [] });
    }

    onSearchInput(ev) {
        this.state.options.search_value = ev.target.value;
    }

    onSearchKeydown(ev) {
        if (ev.key === "Enter") {
            this.applyOptions({ search_value: this.state.options.search_value || "" });
        }
    }

    onComparisonFilterChange(ev) {
        this.applyOptions({
            comparison: { ...(this.state.options.comparison || {}), filter: ev.target.value },
        });
    }

    onComparisonNumberChange(ev) {
        this.applyOptions({
            comparison: {
                ...(this.state.options.comparison || {}),
                number_period: parseInt(ev.target.value || "1", 10),
            },
        });
    }

    toggleJournal(id) {
        const ids = new Set(this.state.options.journal_ids || []);
        if (ids.has(id)) {
            ids.delete(id);
        } else {
            ids.add(id);
        }
        this.applyOptions({ journal_ids: [...ids] });
    }

    toggleAnalytic(id) {
        const ids = new Set(this.state.options.analytic_account_ids || []);
        if (ids.has(id)) {
            ids.delete(id);
        } else {
            ids.add(id);
        }
        this.applyOptions({ analytic_account_ids: [...ids] });
    }

    toggleCompany(id) {
        const ids = new Set(this.state.options.company_ids || []);
        if (ids.has(id)) {
            ids.delete(id);
        } else {
            ids.add(id);
        }
        this.applyOptions({ company_ids: [...ids] });
    }

    toggleLine(line) {
        if (!line.unfoldable) {
            return;
        }
        const unfolded = new Set(this.state.options.unfolded_lines || []);
        if (unfolded.has(line.id)) {
            unfolded.delete(line.id);
        } else {
            unfolded.add(line.id);
        }
        this.applyOptions({ unfold_all: false, unfolded_lines: [...unfolded] });
    }

    async openJournalItems(line, columnKey) {
        const action = await this.orm.call("account.report", "abr_open_journal_items", [
            [this.reportId],
            this._optionsPayload(),
            line.id,
            columnKey || null,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    async exportXlsx() {
        const action = await this.orm.call("account.report", "abr_export_xlsx", [
            [this.reportId],
            this._optionsPayload(),
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    async exportPdf() {
        const action = await this.orm.call("account.report", "abr_export_pdf", [
            [this.reportId],
            this._optionsPayload(),
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    formatValue(value) {
        const amount = value || 0;
        const decimals = this.state.options.decimal_places ?? 2;
        const formatted = amount.toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
        return floatIsZero(amount) ? formatted : formatted;
    }

    isZero(value) {
        return Math.abs(value || 0) < Math.pow(10, -(this.state.options.decimal_places ?? 2));
    }

    linePadding(line) {
        return `${Math.max(0, (line.level || 0) - 1) * 16}px`;
    }
}

function floatIsZero(value) {
    return Math.abs(value || 0) < 0.0000001;
}

registry.category("actions").add("account_balance_report", AccountBalanceReportAction);
