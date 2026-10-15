from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, get_datetime, today

from erpnext.setup.doctype.employee.test_employee import make_employee
from hrms.hr.doctype.attendance.attendance import mark_attendance
from hrms.hr.doctype.shift_type.test_shift_type import setup_shift_type

from attendance_correction_tool.attendance_correction_tool.services.attendance_correction_service import (
	AttendanceCorrectionService,
)

test_ignore = ["Attendance", "Company", "Employee", "Shift Type", "User"]


class TestAttendanceCorrectionRun(FrappeTestCase):
	def test_enqueue_returns_stable_job_id_when_queued_after_commit(self):
		correction_run = MagicMock()
		correction_run.status = "Previewed"
		correction_run.total_candidates = 1
		correction_run.name = "ACR-TEST-00001"
		service = AttendanceCorrectionService(correction_run)

		with (
			patch.object(service, "_check_attendance_permissions"),
			patch("frappe.enqueue", return_value=None) as enqueue,
		):
			result = service.enqueue()

		self.assertEqual(result["job_id"], "attendance-correction-ACR-TEST-00001")
		self.assertEqual(result["status"], "Queued")
		enqueue.assert_called_once()

	def test_corrects_auto_absence_from_late_checkins(self):
		company = "_Test Company"
		attendance_date = add_days(today(), -2)
		if not frappe.db.exists("Employment Type", "Intern"):
			frappe.get_doc(
				{"doctype": "Employment Type", "employee_type_name": "Intern"}
			).insert()
		shift = setup_shift_type(
			shift_type="_Test Attendance Correction Shift",
			start_time="08:00:00",
			end_time="17:00:00",
		)
		employee = make_employee("attendance-correction-test@example.com", company=company)
		employee_doc = frappe.get_doc("Employee", employee)
		employee_doc.default_shift = shift.name
		employee_doc.save()

		old_attendance = mark_attendance(employee, attendance_date, "Absent", shift.name)
		frappe.get_doc("Attendance", old_attendance).add_comment(
			text="Employee was marked Absent due to missing Employee Checkins."
		)

		checkins = []
		for checkin_time in ("08:00:00", "17:00:00"):
			checkins.append(
				frappe.get_doc(
					{
						"doctype": "Employee Checkin",
						"employee": employee,
						"time": get_datetime(f"{attendance_date} {checkin_time}"),
					}
				).insert()
			)

		correction_run = frappe.get_doc(
			{
				"doctype": "Attendance Correction Run",
				"company": company,
				"from_date": attendance_date,
				"to_date": attendance_date,
				"employee": employee,
				"shift": shift.name,
			}
		).insert()
		AttendanceCorrectionService(correction_run).preview()
		correction_run.reload()

		self.assertEqual(correction_run.total_candidates, 1)
		self.assertEqual(correction_run.results[0].result, "Ready")
		self.assertEqual(correction_run.results[0].corrected_status, "Present")
		self.assertEqual(correction_run.results[0].working_hours, 9)

		AttendanceCorrectionService(correction_run).run()
		correction_run.reload()
		new_attendance = correction_run.results[0].new_attendance

		self.assertEqual(frappe.db.get_value("Attendance", old_attendance, "docstatus"), 2)
		self.assertEqual(frappe.db.get_value("Attendance", new_attendance, "status"), "Present")
		self.assertEqual(frappe.db.get_value("Attendance", new_attendance, "working_hours"), 9)
		self.assertEqual(correction_run.corrected_count, 1)
		self.assertEqual(correction_run.status, "Completed")
		for checkin in checkins:
			self.assertEqual(frappe.db.get_value("Employee Checkin", checkin.name, "attendance"), new_attendance)

	def test_rejects_employee_from_another_company(self):
		employee = frappe.get_all("Employee", fields=["name", "company"], limit=1)
		if not employee:
			self.skipTest("No Employee available")

		with patch("frappe.db.get_value", return_value="Another Company"):
			with self.assertRaises(frappe.ValidationError):
				AttendanceCorrectionService.validate_filters(
					frappe._dict(
						company=employee[0].company,
						employee=employee[0].name,
						from_date="2026-01-01",
						to_date="2026-01-02",
					)
				)
	def test_rejects_invalid_date_range(self):
		with self.assertRaises(frappe.ValidationError):
			AttendanceCorrectionService.validate_filters(
				frappe._dict(
					company="Test Company",
					employee=None,
					from_date="2026-01-02",
					to_date="2026-01-01",
				)
			)

	def test_rejects_date_range_over_one_year(self):
		with self.assertRaises(frappe.ValidationError):
			AttendanceCorrectionService.validate_filters(
				frappe._dict(
					company="Test Company",
					employee=None,
					from_date="2025-01-01",
					to_date="2026-01-03",
				)
			)
