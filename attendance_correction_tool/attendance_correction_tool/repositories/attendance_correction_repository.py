from datetime import datetime, time, timedelta

import frappe
from frappe.utils import create_batch, getdate


AUTO_ABSENCE_COMMENT = "%missing Employee Checkins%"
DUPLICATE_SKIP_COMMENT = "%already marked for the date%"


class AttendanceCorrectionRepository:
	def get_absences_in_scope(self, correction_run) -> list[frappe._dict]:
		filters = {
			"company": correction_run.company,
			"attendance_date": ["between", [correction_run.from_date, correction_run.to_date]],
			"docstatus": 1,
			"status": "Absent",
		}
		if correction_run.employee:
			filters["employee"] = correction_run.employee
		if correction_run.shift:
			filters["shift"] = correction_run.shift

		attendances = frappe.get_all(
			"Attendance",
			filters=filters,
			fields=[
				"name",
				"employee",
				"employee_name",
				"attendance_date",
				"status",
				"shift",
				"working_hours",
			],
			order_by="attendance_date, employee",
		)
		auto_attendance_names: set[str] = set()
		for names in create_batch([row.name for row in attendances], 500):
			auto_attendance_names.update(
				frappe.get_all(
					"Comment",
					filters={
						"reference_doctype": "Attendance",
						"reference_name": ["in", names],
						"comment_type": "Comment",
						"content": ["like", AUTO_ABSENCE_COMMENT],
					},
					pluck="reference_name",
				)
			)

		for attendance in attendances:
			attendance.is_auto_absence = attendance.name in auto_attendance_names

		return attendances

	def get_eligible_checkins(self, attendance: frappe._dict) -> list[frappe._dict]:
		attendance_date = getdate(attendance.attendance_date)
		start = datetime.combine(attendance_date, time.min)
		end = start + timedelta(days=1)
		logs = frappe.get_all(
			"Employee Checkin",
			filters={
				"employee": attendance.employee,
				"shift": attendance.shift,
				"shift_start": ["between", [start, end - timedelta(microseconds=1)]],
				"attendance": ["is", "not set"],
				"offshift": 0,
			},
			fields=[
				"name",
				"employee",
				"log_type",
				"time",
				"shift",
				"shift_start",
				"shift_end",
				"shift_actual_start",
				"shift_actual_end",
				"device_id",
				"skip_auto_attendance",
			],
			order_by="time",
		)
		if not logs:
			return []

		skipped_names = [row.name for row in logs if row.skip_auto_attendance]
		if not skipped_names:
			return logs

		auto_skipped_names = set(
			frappe.get_all(
				"Comment",
				filters={
					"reference_doctype": "Employee Checkin",
					"reference_name": ["in", skipped_names],
					"comment_type": "Comment",
					"content": ["like", DUPLICATE_SKIP_COMMENT],
				},
				pluck="reference_name",
			)
		)
		return [row for row in logs if not row.skip_auto_attendance or row.name in auto_skipped_names]

	def lock_attendance(self, attendance_name: str) -> bool:
		rows = frappe.db.sql(
			"""
			select name
			from `tabAttendance`
			where name = %s and docstatus = 1 and status = 'Absent'
			for update
			""",
			attendance_name,
		)
		return bool(rows)

	def reset_auto_skipped_checkins(self, logs: list[frappe._dict]) -> None:
		for log in logs:
			if log.skip_auto_attendance:
				frappe.db.set_value("Employee Checkin", log.name, "skip_auto_attendance", 0, update_modified=False)
				log.skip_auto_attendance = 0
