"""One-off generator for the synthetic Solution Design Document used by the
CASE-1001 sample case. Run once after installing requirements.txt:

    .venv\\Scripts\\python.exe scripts\\generate_sample_sdd.py
"""

import os

import docx

OUTPUT_PATH = os.path.join(
    os.path.dirname(__file__), "..", "sample_cases", "CASE-1001", "SDD.docx"
)


def build():
    doc = docx.Document()

    doc.add_heading("Solution Design Document", level=0)
    doc.add_heading("Patient Intake Duplicate Check Enhancement", level=1)

    doc.add_heading("Overview", level=2)
    doc.add_paragraph(
        "Customer: Meridian Health Partners"
    )
    doc.add_paragraph(
        "Package: Elixir - EHR Module"
    )
    doc.add_paragraph(
        "This document describes a customer-specific customization built on top of the "
        "Elixir base package's Patient Matching Service, adding a duplicate-check step to "
        "the Patient Intake process using the patient's Insurance ID."
    )

    doc.add_heading("Business Requirement", level=2)
    doc.add_paragraph(
        "Front-desk staff at Meridian Health Partners frequently register walk-in patients "
        "who do not yet have insurance information on file. The clinic requires that: (1) "
        "patients with a known Insurance ID are automatically checked for duplicates against "
        "existing Patient__c records, and (2) patients without an Insurance ID at intake time "
        "are still allowed to be registered, but flagged for manual review by the front-desk "
        "supervisor once insurance information becomes available."
    )

    doc.add_heading("Design", level=2)
    doc.add_paragraph(
        "A custom Apex trigger, PatientIntakeTrigger, fires on Patient__c before insert and "
        "delegates to a custom handler class, PatientIntakeTriggerHandler.handleBeforeInsert()."
    )
    doc.add_paragraph(
        "For each new Patient__c record, the handler MUST first check whether "
        "Insurance_Id__c is blank or null:"
    )
    doc.add_paragraph(
        "- If Insurance_Id__c is blank/null: skip the duplicate check entirely. Set "
        "Needs_Manual_Review__c = true and Duplicate_Check_Status__c = 'Skipped - Missing "
        "Insurance ID'. The record must still save successfully.",
        style="List Bullet",
    )
    doc.add_paragraph(
        "- If Insurance_Id__c is populated: normalize the value (trim whitespace, convert to "
        "lowercase) and pass it to the Elixir base package method "
        "ElixirPatientMatchingService.findDuplicatesByInsuranceId(String insuranceId). If any "
        "duplicates are returned, block the save with a validation error.",
        style="List Bullet",
    )

    doc.add_heading("Field Mappings", level=2)
    table = doc.add_table(rows=1, cols=3)
    table.style = "Light Grid Accent 1"
    hdr = table.rows[0].cells
    hdr[0].text = "Field API Name"
    hdr[1].text = "Type"
    hdr[2].text = "Purpose"
    rows = [
        ("Insurance_Id__c", "Text(30)", "Patient's insurance identifier, optional at intake"),
        ("Needs_Manual_Review__c", "Checkbox", "Set true when duplicate check was skipped"),
        (
            "Duplicate_Check_Status__c",
            "Picklist",
            "Tracks whether the duplicate check ran, was skipped, or found a match",
        ),
    ]
    for api_name, ftype, purpose in rows:
        cells = table.add_row().cells
        cells[0].text = api_name
        cells[1].text = ftype
        cells[2].text = purpose

    doc.add_heading("Known Limitations", level=2)
    doc.add_paragraph(
        "Per the Elixir Developer Guide, section 4.2 (Matching Service Contract): "
        "ElixirPatientMatchingService.findDuplicatesByInsuranceId does not perform its own "
        "null-check or normalization of the insuranceId parameter. It is the caller's "
        "responsibility (i.e. this customization's trigger handler) to null-check and "
        "normalize the value before invoking it. The base package method will throw a "
        "NullPointerException if passed a null argument - this is documented, expected "
        "behavior for the base package, not a defect."
    )

    doc.add_heading("Sign-off", level=2)
    doc.add_paragraph("Approved by: Meridian Health Partners - Clinical Operations")
    doc.add_paragraph("Delivered by: Elixir Implementation Team")

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    doc.save(OUTPUT_PATH)
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
