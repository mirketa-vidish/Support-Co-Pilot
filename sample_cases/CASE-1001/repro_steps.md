# Issue Replication Steps - CASE-1001

**Customer:** Meridian Health Partners
**Module:** EHR - Patient Intake
**Severity:** High (blocks patient registration)

## Steps to Reproduce

1. Log in as a Patient Intake Coordinator user.
2. Navigate to the "New Patient Intake" screen flow.
3. Fill in required fields: First Name, Last Name, Date of Birth, Phone.
4. Leave the "Insurance ID" field **blank** (this is a valid scenario - the
   patient may not have insurance information available yet at intake time,
   per the Solution Design Document section "Design").
5. Click Save.

## Expected Result

Per the Solution Design Document, when Insurance ID is blank the duplicate
check should be skipped, and the record should save successfully with:

- `Needs_Manual_Review__c` = true
- `Duplicate_Check_Status__c` = "Skipped - Missing Insurance ID"

## Actual Result

Save fails with the error:

> Apex trigger PatientIntakeTrigger caused an unexpected exception, contact
> your administrator: PatientIntakeTrigger: execution of BeforeInsert caused
> by: System.NullPointerException: Attempt to de-reference a null object:
> Class.PatientIntakeTriggerHandler.handleBeforeInsert: line 8, column 1

No patient record is created. This blocks intake for any walk-in patient
without insurance information on file, which is a common scenario for this
customer (roughly 15% of intakes per their front-desk team).

## Attachments

- `debug_log.log` - FINEST level, captured during a reproduction run as the
  affected Patient Intake Coordinator user.
- `SDD.docx` - Solution Design Document for this customization.
