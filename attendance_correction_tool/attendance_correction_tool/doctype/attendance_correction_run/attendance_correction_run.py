# Copyright (c) 2026, Ahmad and contributors
# For license information, please see license.txt

from typing import TYPE_CHECKING

import frappe
from frappe import _
from frappe.model.document import Document

from attendance_correction_tool.attendance_correction_tool.services.attendance_correction_service import (
	AttendanceCorrectionService,
)

if TYPE_CHECKING:
	from frappe.types import DF

	from attendance_correction_tool.attendance_correction_tool.doctype.attendance_correction_result.attendance_correction_result import (
		AttendanceCorrectionResult,
	)


class AttendanceCorrectionRun(Document):
	if TYPE_CHECKING:
		company: DF.Link
		corrected_count: DF.Int
		failed_count: DF.Int
		from_date: DF.Date
		requested_by: DF.Link | None
		results: DF.Table[AttendanceCorrectionResult]
		scanned_count: DF.Int
		skipped_count: DF.Int
		status: DF.Literal["Draft", "Previewed", "Queued", "Running", "Completed", "Completed with Errors", "Failed"]
		to_date: DF.Date
		total_candidates: DF.Int

	def before_insert(self) -> None:
		self.requested_by = frappe.session.user

	def validate(self) -> None:
		AttendanceCorrectionService.validate_filters(self)
		self._validate_filter_changes()

	def _validate_filter_changes(self) -> None:
		if self.is_new():
			return

		old_doc = self.get_doc_before_save()
		if not old_doc or old_doc.status == "Draft":
			return

		for fieldname in ("company", "from_date", "to_date", "employee", "shift"):
			if self.has_value_changed(fieldname):
				frappe.throw(_("Filters cannot be changed after this correction run has been previewed."))

	@frappe.whitelist()
	def preview(self) -> dict:
		self.check_permission("write")
		return AttendanceCorrectionService(self).preview()

	@frappe.whitelist()
	def enqueue_correction(self) -> dict:
		self.check_permission("write")
		return AttendanceCorrectionService(self).enqueue()
