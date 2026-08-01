# RuntimeInfrastructureProfileReplaceRequest

Complete optimistic replacement of one infrastructure Profile.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**expected_version** | **int** |  | 
**display_name** | **str** |  | 
**description** | **str** |  | 
**lifecycle** | [**RuntimeProfileLifecycle**](RuntimeProfileLifecycle.md) |  | 
**spec** | [**RuntimeInfrastructureProfileSpec**](RuntimeInfrastructureProfileSpec.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_infrastructure_profile_replace_request import RuntimeInfrastructureProfileReplaceRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeInfrastructureProfileReplaceRequest from a JSON string
runtime_infrastructure_profile_replace_request_instance = RuntimeInfrastructureProfileReplaceRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeInfrastructureProfileReplaceRequest.to_json())

# convert the object into a dict
runtime_infrastructure_profile_replace_request_dict = runtime_infrastructure_profile_replace_request_instance.to_dict()
# create an instance of RuntimeInfrastructureProfileReplaceRequest from a dict
runtime_infrastructure_profile_replace_request_from_dict = RuntimeInfrastructureProfileReplaceRequest.from_dict(runtime_infrastructure_profile_replace_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


