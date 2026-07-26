# RuntimeExecutionPolicyAuditListResponse

Metadata-only authorized execution-policy audit collection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeExecutionPolicyAuditEventResponse]**](RuntimeExecutionPolicyAuditEventResponse.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_policy_audit_list_response import RuntimeExecutionPolicyAuditListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionPolicyAuditListResponse from a JSON string
runtime_execution_policy_audit_list_response_instance = RuntimeExecutionPolicyAuditListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionPolicyAuditListResponse.to_json())

# convert the object into a dict
runtime_execution_policy_audit_list_response_dict = runtime_execution_policy_audit_list_response_instance.to_dict()
# create an instance of RuntimeExecutionPolicyAuditListResponse from a dict
runtime_execution_policy_audit_list_response_from_dict = RuntimeExecutionPolicyAuditListResponse.from_dict(runtime_execution_policy_audit_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


