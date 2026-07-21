// CUSTOMIZATION for Meridian Health Partners - Patient Intake Duplicate Check
// Built on top of the Elixir base package (EHR module).
// Reference: Solution Design Document "Patient Intake Duplicate Check Enhancement", section "Design".
public class PatientIntakeTriggerHandler {

    public static void handleBeforeInsert(List<Patient__c> newPatients) {
        for (Patient__c p : newPatients) {
            String insuranceId = p.Insurance_Id__c;

            // TODO/BUG: SDD section "Design" requires checking for blank/null
            // Insurance_Id__c here, skipping the duplicate check, and setting
            // Needs_Manual_Review__c = true + Duplicate_Check_Status__c =
            // 'Skipped - Missing Insurance ID' before ever touching insuranceId.
            // That branch was never implemented - insuranceId is normalized
            // unconditionally below, which throws when it is null.
            String normalizedId = insuranceId.trim().toLowerCase();

            List<Patient__c> duplicates =
                ElixirPatientMatchingService.findDuplicatesByInsuranceId(normalizedId);

            if (!duplicates.isEmpty()) {
                p.addError('A patient with this Insurance ID already exists.');
            }
        }
    }
}
