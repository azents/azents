# RuntimeExecutionProfileReplaceRequest

Complete optimistic Profile replacement.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**policy** | [**RuntimeExecutionPolicyDocument**](RuntimeExecutionPolicyDocument.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_profile_replace_request import RuntimeExecutionProfileReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionProfileReplaceRequest from a JSON string
runtime_execution_profile_replace_request_instance = RuntimeExecutionProfileReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionProfileReplaceRequest.to_json())

# convert the object into a dict
runtime_execution_profile_replace_request_dict = runtime_execution_profile_replace_request_instance.to_dict()
# create an instance of RuntimeExecutionProfileReplaceRequest from a dict
runtime_execution_profile_replace_request_from_dict = RuntimeExecutionProfileReplaceRequest.from_dict(runtime_execution_profile_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


