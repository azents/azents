# RuntimeExecutionPolicyRestriction

Restrictive-only Workspace or Agent policy contribution.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**schema_version** | **int** |  | 
**image_build** | [**RuntimeExecutionBooleanRestriction**](RuntimeExecutionBooleanRestriction.md) |  | 
**container_run** | [**RuntimeExecutionBooleanRestriction**](RuntimeExecutionBooleanRestriction.md) |  | 
**compose** | [**RuntimeExecutionBooleanRestriction**](RuntimeExecutionBooleanRestriction.md) |  | 
**resources** | [**RuntimeExecutionResourceRestriction**](RuntimeExecutionResourceRestriction.md) |  | 
**engine_storage** | [**RuntimeExecutionStorageRestriction**](RuntimeExecutionStorageRestriction.md) |  | 
**network_egress** | [**RuntimeExecutionNetworkRestriction**](RuntimeExecutionNetworkRestriction.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_execution_policy_restriction import RuntimeExecutionPolicyRestriction

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionPolicyRestriction from a JSON string
runtime_execution_policy_restriction_instance = RuntimeExecutionPolicyRestriction.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionPolicyRestriction.to_json())

# convert the object into a dict
runtime_execution_policy_restriction_dict = runtime_execution_policy_restriction_instance.to_dict()
# create an instance of RuntimeExecutionPolicyRestriction from a dict
runtime_execution_policy_restriction_from_dict = RuntimeExecutionPolicyRestriction.from_dict(runtime_execution_policy_restriction_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


