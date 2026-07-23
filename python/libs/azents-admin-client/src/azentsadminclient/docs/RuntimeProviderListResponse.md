# RuntimeProviderListResponse

Provider inventory response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeProviderResponse]**](RuntimeProviderResponse.md) |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_list_response import RuntimeProviderListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderListResponse from a JSON string
runtime_provider_list_response_instance = RuntimeProviderListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderListResponse.to_json())

# convert the object into a dict
runtime_provider_list_response_dict = runtime_provider_list_response_instance.to_dict()
# create an instance of RuntimeProviderListResponse from a dict
runtime_provider_list_response_from_dict = RuntimeProviderListResponse.from_dict(runtime_provider_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


