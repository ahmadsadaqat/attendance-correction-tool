// Copyright (c) 2026, Ahmad and contributors
// For license information, please see license.txt

frappe.ui.form.on("Attendance Correction Run", {
	setup(frm) {
		frm.set_query("employee", () => ({
			filters: { company: frm.doc.company },
		}));
	},

	refresh(frm) {
		if (frm.is_new()) {
			return;
		}

		if (frm.doc.status === "Draft") {
			frm.add_custom_button(__("Preview Corrections"), async () => {
				await frm.call({
					method: "preview",
					freeze: true,
					freeze_message: __("Finding auto-marked absences and matching check-ins..."),
				});
				await frm.reload_doc();
			});
		}

		if (frm.doc.status === "Previewed" && frm.doc.total_candidates > 0) {
			frm.add_custom_button(__("Run Corrections"), () => {
				frappe.confirm(
					__("This will cancel each eligible auto-marked absence and create a corrected submitted Attendance from its check-ins. Continue?"),
					async () => {
						await frm.call({ method: "enqueue_correction", freeze: true });
						await frm.reload_doc();
					},
				);
			}, __("Actions"));
		}

		if (["Queued", "Running"].includes(frm.doc.status)) {
			frm.dashboard.set_headline_alert(
				__("Correction is running in the background. Reload this document to see progress."),
				"blue",
			);
		}
	},

	validate(frm) {
		if (frm.doc.from_date && frm.doc.to_date && frm.doc.from_date > frm.doc.to_date) {
			frappe.throw(__("From Date cannot be after To Date."));
		}
	},
});
