/** @odoo-module **/

import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { Component, onWillStart, useState } from "@odoo/owl";

const DATE_FILTERS = [
    { value: "today", label: "Today" },
    { value: "this_month", label: "This Month" },
    { value: "previous_month", label: "Last Month" },
    { value: "this_quarter", label: "This Quarter" },
    { value: "previous_quarter", label: "Last Quarter" },
    { value: "this_year", label: "This Year" },
    { value: "previous_year", label: "Last Year" },
];

export class AccountBalanceReportAction extends Component {
    static template = "account_balance_reports.AccountBalanceReportAction";
    static props = { "*": true };

    setup() {
        this.orm = useService("orm");
        this.action = useService("action");
        this.notification = useService("notification");
        this.dateFilters = DATE_FILTERS;
        this.state = useState({
            loading: true,
            reportName: "",
            handler: "balance_sheet",
            options: {},
            lines: [],
        });
        onWillStart(async () => {
            await this.reload();
        });
    }

    get reportId() {
        const ctx = this.props.action.context || {};
        return ctx.report_id || ctx.active_id;
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
        // Backend already returns the visible flattened tree for the current unfold state.
        return this.state.lines || [];
    }

    async reload() {
        this.state.loading = true;
        try {
            const payload = await this.orm.call("account.report", "abr_get_report_payload", [
                [this.reportId],
                this.state.options && this.state.options.report_id ? this.state.options : {},
            ]);
            this.state.options = payload.options;
            this.state.lines = payload.lines;
            this.state.reportName = payload.report_name;
            this.state.handler = payload.handler;
        } finally {
            this.state.loading = false;
        }
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

    onAllEntriesChange(ev) {
        this.applyOptions({ all_entries: ev.target.checked });
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

    onSearchApply() {
        this.applyOptions({ search_value: this.state.options.search_value || "" });
    }

    onComparisonFilterChange(ev) {
        const comparison = {
            ...(this.state.options.comparison || {}),
            filter: ev.target.value,
        };
        this.applyOptions({ comparison });
    }

    onComparisonNumberChange(ev) {
        const comparison = {
            ...(this.state.options.comparison || {}),
            number_period: parseInt(ev.target.value || "1", 10),
        };
        this.applyOptions({ comparison });
    }

    onJournalChange(ev) {
        const selected = Array.from(ev.target.selectedOptions).map((o) => parseInt(o.value, 10));
        this.applyOptions({ journal_ids: selected });
    }

    onCompanyChange(ev) {
        const selected = Array.from(ev.target.selectedOptions).map((o) => parseInt(o.value, 10));
        this.applyOptions({ company_ids: selected });
    }

    toggleLine(line) {
        if (!line.unfoldable) {
            return;
        }
        const unfolded = new Set(this.state.options.unfolded_lines || []);
        if (unfolded.has(line.id) || line.unfolded) {
            unfolded.delete(line.id);
        } else {
            unfolded.add(line.id);
        }
        this.applyOptions({ unfold_all: false, unfolded_lines: [...unfolded] });
    }

    async openJournalItems(line) {
        const action = await this.orm.call("account.report", "abr_open_journal_items", [
            [this.reportId],
            this.state.options,
            line.id,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    async exportXlsx() {
        const action = await this.orm.call("account.report", "abr_export_xlsx", [
            [this.reportId],
            this.state.options,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    async exportPdf() {
        const action = await this.orm.call("account.report", "abr_export_pdf", [
            [this.reportId],
            this.state.options,
        ]);
        if (action) {
            this.action.doAction(action);
        }
    }

    formatValue(value) {
        const amount = value || 0;
        const decimals = this.state.options.decimal_places ?? 2;
        return amount.toLocaleString(undefined, {
            minimumFractionDigits: decimals,
            maximumFractionDigits: decimals,
        });
    }

    linePadding(line) {
        return `${(line.level || 0) * 16}px`;
    }
}

registry.category("actions").add("account_balance_report", AccountBalanceReportAction);
