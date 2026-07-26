# RuntimeExecutionPolicyAuditEventResponse

Metadata-only authorized execution-policy audit event.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**event_type** | [**RuntimeExecutionAuditEventType**](RuntimeExecutionAuditEventType.md) |  | 
**management_layer** | [**RuntimeExecutionManagementLayer**](RuntimeExecutionManagementLayer.md) |  | 
**target_id** | **str** |  | 
**correlation_id** | **str** |  | 
**classification** | [**RuntimeExecutionChangeDirection**](RuntimeExecutionChangeDirection.md) |  | 
**changed_paths** | **List[str]** |  | 
**impact_counts** | **Dict[str, int]** |  | 
**reason_code** | **str** |  | 
**outcome_code** | **str** |  | 
**actor_user_id** | **str** |  | 
**actor_workspace_user_id** | **str** |  | 
**system_authority** | **bool** |  | 
**before_digest** | **str** |  | 
**after_digest** | **str** |  | 
**created_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_policy_audit_event_response import RuntimeExecutionPolicyAuditEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionPolicyAuditEventResponse from a JSON string
runtime_execution_policy_audit_event_response_instance = RuntimeExecutionPolicyAuditEventResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionPolicyAuditEventResponse.to_json())

# convert the object into a dict
runtime_execution_policy_audit_event_response_dict = runtime_execution_policy_audit_event_response_instance.to_dict()
# create an instance of RuntimeExecutionPolicyAuditEventResponse from a dict
runtime_execution_policy_audit_event_response_from_dict = RuntimeExecutionPolicyAuditEventResponse.from_dict(runtime_execution_policy_audit_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


