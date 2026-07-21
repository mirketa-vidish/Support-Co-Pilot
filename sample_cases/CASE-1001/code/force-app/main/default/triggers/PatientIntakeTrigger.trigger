// CUSTOMIZATION for Meridian Health Partners - Patient Intake
trigger PatientIntakeTrigger on Patient__c (before insert) {
    if (Trigger.isBefore && Trigger.isInsert) {
        PatientIntakeTriggerHandler.handleBeforeInsert(Trigger.new);
    }
}
