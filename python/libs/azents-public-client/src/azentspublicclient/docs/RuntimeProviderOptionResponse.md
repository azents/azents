# RuntimeProviderOptionResponse

Safe Provider option for Workspace and Agent preference surfaces.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider_id** | **str** |  | 
**display_name** | **str** |  | 
**kind** | **str** |  | 
**scope** | **str** |  | 
**availability_mode** | **str** |  | 
**capabilities** | **Dict[str, object]** |  | 
**accepted_contract_revision_id** | **str** |  | 
**active_config_revision_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.runtime_provider_option_response import RuntimeProviderOptionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderOptionResponse from a JSON string
runtime_provider_option_response_instance = RuntimeProviderOptionResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderOptionResponse.to_json())

# convert the object into a dict
runtime_provider_option_response_dict = runtime_provider_option_response_instance.to_dict()
# create an instance of RuntimeProviderOptionResponse from a dict
runtime_provider_option_response_from_dict = RuntimeProviderOptionResponse.from_dict(runtime_provider_option_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


