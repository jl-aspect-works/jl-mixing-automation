# Runtime Templates

JL Mixing Automation v1.1 ships six canonical Markdown templates:

- `Intake_Report.md`
- `Project_Notes.md`
- `Preparation_Report.md`
- `Revision_Notes.md`
- `Delivery_Notes.md`
- `Recall_Sheet.md`

`Intake_Report.md` is the only shared managed document. `validate-intake`
replaces only the text between its exact automated-section markers. All other
Markdown files are fully user-owned after creation.

The `studio/` and `client/` subdirectories contain the JSON construction
templates used by `new-studio` and `new-client`.
