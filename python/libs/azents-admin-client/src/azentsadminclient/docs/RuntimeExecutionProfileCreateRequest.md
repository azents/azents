# RuntimeExecutionProfileCreateRequest

Create one ordinary active Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**profile_id** | **str** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**policy** | [**RuntimeExecutionPolicyDocument**](RuntimeExecutionPolicyDocument.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_profile_create_request import RuntimeExecutionProfileCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionProfileCreateRequest from a JSON string
runtime_execution_profile_create_request_instance = RuntimeExecutionProfileCreateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionProfileCreateRequest.to_json())

# convert the object into a dict
runtime_execution_profile_create_request_dict = runtime_execution_profile_create_request_instance.to_dict()
# create an instance of RuntimeExecutionProfileCreateRequest from a dict
runtime_execution_profile_create_request_from_dict = RuntimeExecutionProfileCreateRequest.from_dict(runtime_execution_profile_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


