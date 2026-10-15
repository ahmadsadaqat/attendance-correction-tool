frappe.listview_settings["Attendance Correction Run"] = {
	get_indicator(doc) {
		const colors = {
			Draft: "grey",
			Previewed: "blue",
			Queued: "orange",
			Running: "orange",
			Completed: "green",
			"Completed with Errors": "yellow",
			Failed: "red",
		};
		return [__(doc.status), colors[doc.status] || "grey", `status,=,${doc.status}`];
	},
};
