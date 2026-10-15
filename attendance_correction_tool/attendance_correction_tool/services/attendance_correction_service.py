import traceback

import frappe
from frappe import _
from frappe.utils import date_diff, getdate, now, now_datetime

from hrms.hr.doctype.employee_checkin.employee_checkin import mark_attendance_and_link_log

from attendance_correction_tool.attendance_correction_tool.repositories.attendance_correction_repository import (
	AttendanceCorrectionRepository,
)


MAX_DATE_RANGE_DAYS = 366


class AttendanceCorrectionService:
	def __init__(self, correction_run):
		self.correction_run = correction_run
		self.repository = AttendanceCorrectionRepository()

	@staticmethod
	def validate_filters(correction_run) -> None:
		if not correction_run.from_date or not correction_run.to_date:
			return
		if getdate(correction_run.from_date) > getdate(correction_run.to_date):
			frappe.throw(_("From Date cannot be after To Date."))
		if date_diff(correction_run.to_date, correction_run.from_date) + 1 > MAX_DATE_RANGE_DAYS:
			frappe.throw(_("The correction period cannot exceed {0} days.").format(MAX_DATE_RANGE_DAYS))
		if correction_run.employee:
			employee_company = frappe.db.get_value("Employee", correction_run.employee, "company")
			if employee_company != correction_run.company:
				frappe.throw(_("The selected Employee does not belong to the selected Company."))

	def preview(self) -> dict:
		if self.correction_run.status != "Draft":
			frappe.throw(_("Only a Draft correction run can be previewed."))

		self._check_attendance_permissions()
		self.correction_run.set("results", [])
		rows = self._evaluate_scope()
		ready_count = sum(row["result"] == "Ready" for row in rows)
		skipped_count = sum(row["result"] == "Skipped" for row in rows)

		for row in rows:
			self.correction_run.append("results", row)
		self.correction_run.update(
			{
				"status": "Previewed",
				"scanned_count": len(rows),
				"total_candidates": ready_count,
				"corrected_count": 0,
				"skipped_count": skipped_count,
				"failed_count": 0,
				"error_log": None,
			}
		)
		self.correction_run.save()
		frappe.msgprint(
			_("Preview complete: {0} attendance record(s) are ready to correct.").format(ready_count),
			indicator="blue" if ready_count else "orange",
		)
		return {"ready": ready_count, "skipped": skipped_count}

	def enqueue(self) -> dict:
		if self.correction_run.status != "Previewed":
			frappe.throw(_("Preview this correction run before starting it."))
		if not self.correction_run.total_candidates:
			frappe.throw(_("There are no eligible attendance records to correct."))

		self._check_attendance_permissions()
		self.correction_run.db_set(
			{
				"status": "Queued",
				"requested_by": frappe.session.user,
				"requested_at": now(),
				"completed_at": None,
				"error_log": None,
			}
		)
		job_id = f"attendance-correction-{self.correction_run.name}"
		frappe.enqueue(
			"attendance_correction_tool.attendance_correction_tool.services.attendance_correction_service.run_correction_job",
			queue="long",
			timeout=3600,
			job_id=job_id,
			deduplicate=True,
			enqueue_after_commit=True,
			correction_run_name=self.correction_run.name,
		)
		return {"job_id": job_id, "status": "Queued"}

	def run(self) -> None:
		self.correction_run.db_set("status", "Running")
		self.correction_run.reload()
		self.correction_run.set("results", [])
		rows = self._evaluate_scope()
		corrected = skipped = failed = 0

		for index, row in enumerate(rows, start=1):
			if row["result"] != "Ready":
				skipped += 1
				self.correction_run.append("results", row)
				continue

			try:
				result = self._correct_attendance(row, index)
				corrected += 1
			except Exception as exc:
				frappe.db.rollback(save_point=f"attendance_correction_{index}")
				failed += 1
				result = {**row, "result": "Failed", "details": str(exc)[:500]}
				frappe.log_error(
					title=f"Attendance Correction failed: {row['original_attendance']}",
					message=traceback.format_exc(),
				)
			self.correction_run.append("results", result)

		self.correction_run.update(
			{
				"status": "Completed with Errors" if failed else "Completed",
				"scanned_count": len(rows),
				"total_candidates": sum(row["result"] == "Ready" for row in rows),
				"corrected_count": corrected,
				"skipped_count": skipped,
				"failed_count": failed,
				"completed_at": now(),
			}
		)
		self.correction_run.save(ignore_permissions=True)

	def _evaluate_scope(self) -> list[dict]:
		rows = []
		for attendance in self.repository.get_auto_absences(self.correction_run):
			logs = self.repository.get_eligible_checkins(attendance)
			base_row = {
				"original_attendance": attendance.name,
				"employee": attendance.employee,
				"employee_name": attendance.employee_name,
				"attendance_date": attendance.attendance_date,
				"shift": attendance.shift,
				"original_status": attendance.status,
				"checkin_count": len(logs),
			}
			if not logs:
				rows.append(
					{
						**base_row,
						"result": "Skipped",
						"details": _("No eligible, unlinked Employee Checkins were found."),
					}
				)
				continue

			shift = frappe.get_cached_doc("Shift Type", attendance.shift)
			if not shift.should_mark_attendance(attendance.employee, attendance.attendance_date):
				rows.append(
					{
						**base_row,
						"result": "Skipped",
						"details": _("The attendance date is a holiday for this employee."),
					}
				)
				continue

			status, hours, _late_entry, _early_exit, _in_time, _out_time = shift.get_attendance(logs)
			rows.append(
				{
					**base_row,
					"corrected_status": status,
					"working_hours": hours,
					"result": "Ready",
					"details": _("Calculated from {0} check-in(s).").format(len(logs)),
				}
			)
		return rows

	def _correct_attendance(self, row: dict, index: int) -> dict:
		savepoint = f"attendance_correction_{index}"
		frappe.db.savepoint(savepoint)
		attendance_name = row["original_attendance"]
		if not self.repository.lock_attendance(attendance_name):
			frappe.throw(_("Attendance is no longer a submitted Absent record."))

		logs = self.repository.get_eligible_checkins(frappe._dict(row))
		if not logs:
			frappe.throw(_("The matching check-ins are no longer available."))

		shift = frappe.get_cached_doc("Shift Type", row["shift"])
		status, hours, late_entry, early_exit, in_time, out_time = shift.get_attendance(logs)
		self.repository.reset_auto_skipped_checkins(logs)

		old_attendance = frappe.get_doc("Attendance", attendance_name)
		old_attendance.cancel()
		new_attendance = mark_attendance_and_link_log(
			logs,
			status,
			row["attendance_date"],
			hours,
			late_entry,
			early_exit,
			in_time,
			out_time,
			row["shift"],
		)
		if not new_attendance:
			frappe.throw(_("HRMS could not create the corrected Attendance."))

		new_attendance.add_comment(
			text=_("Created by Attendance Correction Run {0} from cancelled Attendance {1}.").format(
				self.correction_run.name, attendance_name
			)
		)
		return {
			**row,
			"new_attendance": new_attendance.name,
			"corrected_status": status,
			"working_hours": hours,
			"checkin_count": len(logs),
			"result": "Corrected",
			"details": _("Old attendance cancelled and {0} check-in(s) linked.").format(len(logs)),
		}

	def _check_attendance_permissions(self) -> None:
		for permission_type in ("create", "submit", "cancel"):
			if not frappe.has_permission("Attendance", permission_type):
				frappe.throw(
					_("You need {0} permission on Attendance to run this tool.").format(permission_type),
					frappe.PermissionError,
				)


def run_correction_job(correction_run_name: str) -> None:
	correction_run = frappe.get_doc("Attendance Correction Run", correction_run_name)
	try:
		AttendanceCorrectionService(correction_run).run()
	except Exception:
		frappe.db.rollback()
		frappe.db.set_value(
			"Attendance Correction Run",
			correction_run_name,
			{
				"status": "Failed",
				"completed_at": now_datetime(),
				"error_log": traceback.format_exc()[-5000:],
			},
		)
		frappe.db.commit()
		raise
