# RuntimeExecutionProfileListResponse

Paginated Profile collection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeExecutionProfileResponse]**](RuntimeExecutionProfileResponse.md) |  | 
**capabilities** | [**RuntimeExecutionManagementCapabilitiesResponse**](RuntimeExecutionManagementCapabilitiesResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_execution_profile_list_response import RuntimeExecutionProfileListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeExecutionProfileListResponse from a JSON string
runtime_execution_profile_list_response_instance = RuntimeExecutionProfileListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeExecutionProfileListResponse.to_json())

# convert the object into a dict
runtime_execution_profile_list_response_dict = runtime_execution_profile_list_response_instance.to_dict()
# create an instance of RuntimeExecutionProfileListResponse from a dict
runtime_execution_profile_list_response_from_dict = RuntimeExecutionProfileListResponse.from_dict(runtime_execution_profile_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


