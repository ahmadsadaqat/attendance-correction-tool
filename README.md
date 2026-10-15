### Attendance Correction Tool

Attendance Correction Tool for HRMS frappe

This app safely recalculates auto-marked absences after delayed Employee Checkins arrive.

### Usage

1. Open **Attendance Correction Tool > Attendance Correction Run**.
2. Create a run and select the company, date range, and optional employee or shift.
3. Save, then click **Preview Corrections**.
4. Review the calculated status, working hours, and check-in count.
5. Click **Run Corrections** to process the records in the background.

The tool only selects submitted Absent records carrying HRMS's standard auto-absence comment. It does
not overwrite manually marked attendance. During correction, the original Attendance is cancelled, a
new submitted Attendance is calculated using the Shift Type rules, and the matching Employee Checkins
are linked to the new record. Each run retains a row-by-row audit trail.

### Installation

You can install this app using the [bench](https://github.com/frappe/bench) CLI:

```bash
cd $PATH_TO_YOUR_BENCH
bench get-app $URL_OF_THIS_REPO --branch develop
bench install-app attendance_correction_tool
```

### Contributing

This app uses `pre-commit` for code formatting and linting. Please [install pre-commit](https://pre-commit.com/#installation) and enable it for this repository:

```bash
cd apps/attendance_correction_tool
pre-commit install
```

Pre-commit is configured to use the following tools for checking and formatting your code:

- ruff
- eslint
- prettier
- pyupgrade

### License

mit
