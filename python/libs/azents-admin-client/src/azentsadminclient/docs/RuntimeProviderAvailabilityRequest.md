# RuntimeProviderAvailabilityRequest

Workspace allow-list replacement request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_ids** | **List[str]** |  | [optional] 

## Example

```python
from azentsadminclient.models.runtime_provider_availability_request import RuntimeProviderAvailabilityRequest

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderAvailabilityRequest from a JSON string
runtime_provider_availability_request_instance = RuntimeProviderAvailabilityRequest.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderAvailabilityRequest.to_json())

# convert the object into a dict
runtime_provider_availability_request_dict = runtime_provider_availability_request_instance.to_dict()
# create an instance of RuntimeProviderAvailabilityRequest from a dict
runtime_provider_availability_request_from_dict = RuntimeProviderAvailabilityRequest.from_dict(runtime_provider_availability_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


