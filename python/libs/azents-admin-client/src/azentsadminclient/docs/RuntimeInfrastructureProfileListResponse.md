# RuntimeInfrastructureProfileListResponse

Provider-scoped infrastructure Profile list.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeInfrastructureProfileResponse]**](RuntimeInfrastructureProfileResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_list_response import RuntimeInfrastructureProfileListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileListResponse from a JSON string
runtime_infrastructure_profile_list_response_instance = RuntimeInfrastructureProfileListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileListResponse.to_json())

# convert the object into a dict
runtime_infrastructure_profile_list_response_dict = runtime_infrastructure_profile_list_response_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileListResponse from a dict
runtime_infrastructure_profile_list_response_from_dict = RuntimeInfrastructureProfileListResponse.from_dict(runtime_infrastructure_profile_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


