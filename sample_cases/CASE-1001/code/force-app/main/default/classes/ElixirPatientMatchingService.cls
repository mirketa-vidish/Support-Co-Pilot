// ELIXIR BASE PACKAGE - EHR MODULE
// DO NOT MODIFY: this is managed package code. Customer-specific behavior
// must be implemented in customer trigger handlers, not here.
//
// Per the Elixir Developer Guide, section 4.2 ("Matching Service Contract"):
// callers MUST pass a non-null, already-trimmed, already-lowercased
// insuranceId. This method intentionally does not null-check or normalize
// its input, to avoid double-normalizing values callers may have already
// processed differently.
public class ElixirPatientMatchingService {

    public static List<Patient__c> findDuplicatesByInsuranceId(String insuranceId) {
        return [
            SELECT Id, Name, Insurance_Id__c
            FROM Patient__c
            WHERE Insurance_Id__c = :insuranceId
        ];
    }
}
