# RuntimeExecutionPlatformPolicyReplaceRequest

Complete optimistic replacement of the Platform policy.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**policy** | [**RuntimeExecutionPolicyDocument**](RuntimeExecutionPolicyDocument.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_platform_policy_replace_request import RuntimeExecutionPlatformPolicyReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionPlatformPolicyReplaceRequest from a JSON string
runtime_execution_platform_policy_replace_request_instance = RuntimeExecutionPlatformPolicyReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionPlatformPolicyReplaceRequest.to_json())

# convert the object into a dict
runtime_execution_platform_policy_replace_request_dict = runtime_execution_platform_policy_replace_request_instance.to_dict()
# create an instance of RuntimeExecutionPlatformPolicyReplaceRequest from a dict
runtime_execution_platform_policy_replace_request_from_dict = RuntimeExecutionPlatformPolicyReplaceRequest.from_dict(runtime_execution_platform_policy_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


