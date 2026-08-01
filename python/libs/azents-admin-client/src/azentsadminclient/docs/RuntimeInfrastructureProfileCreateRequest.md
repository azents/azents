# RuntimeInfrastructureProfileCreateRequest

Create one Provider-owned typed infrastructure Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | [optional] 
**spec** | [**RuntimeInfrastructureProfileSpec**](RuntimeInfrastructureProfileSpec.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_create_request import RuntimeInfrastructureProfileCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileCreateRequest from a JSON string
runtime_infrastructure_profile_create_request_instance = RuntimeInfrastructureProfileCreateRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileCreateRequest.to_json())

# convert the object into a dict
runtime_infrastructure_profile_create_request_dict = runtime_infrastructure_profile_create_request_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileCreateRequest from a dict
runtime_infrastructure_profile_create_request_from_dict = RuntimeInfrastructureProfileCreateRequest.from_dict(runtime_infrastructure_profile_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


