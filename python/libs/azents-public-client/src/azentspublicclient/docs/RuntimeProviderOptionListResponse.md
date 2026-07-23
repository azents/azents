# RuntimeProviderOptionListResponse

Eligible Provider options response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[RuntimeProviderOptionResponse]**](RuntimeProviderOptionResponse.md) |  | 

## Example

```python
from azentspublicclient.models.runtime_provider_option_list_response import RuntimeProviderOptionListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderOptionListResponse from a JSON string
runtime_provider_option_list_response_instance = RuntimeProviderOptionListResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderOptionListResponse.to_json())

# convert the object into a dict
runtime_provider_option_list_response_dict = runtime_provider_option_list_response_instance.to_dict()
# create an instance of RuntimeProviderOptionListResponse from a dict
runtime_provider_option_list_response_from_dict = RuntimeProviderOptionListResponse.from_dict(runtime_provider_option_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


