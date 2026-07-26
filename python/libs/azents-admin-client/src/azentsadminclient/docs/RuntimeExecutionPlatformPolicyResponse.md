# RuntimeExecutionPlatformPolicyResponse

Current Platform execution-policy ceiling.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**version** | **int** |  | 
**policy** | [**RuntimeExecutionPolicyDocument**](RuntimeExecutionPolicyDocument.md) |  | 
**digest** | **str** |  | 
**updated_by_user_id** | **str** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 
**capabilities** | [**RuntimeExecutionManagementCapabilitiesResponse**](RuntimeExecutionManagementCapabilitiesResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_platform_policy_response import RuntimeExecutionPlatformPolicyResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionPlatformPolicyResponse from a JSON string
runtime_execution_platform_policy_response_instance = RuntimeExecutionPlatformPolicyResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionPlatformPolicyResponse.to_json())

# convert the object into a dict
runtime_execution_platform_policy_response_dict = runtime_execution_platform_policy_response_instance.to_dict()
# create an instance of RuntimeExecutionPlatformPolicyResponse from a dict
runtime_execution_platform_policy_response_from_dict = RuntimeExecutionPlatformPolicyResponse.from_dict(runtime_execution_platform_policy_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


