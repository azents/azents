# RuntimeProviderResponse

Durable Runtime Provider inventory item.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider_id** | **str** |  | 
**scope** | **str** |  | 
**workspace_id** | **str** |  | 
**kind** | **str** |  | 
**display_name** | **str** |  | 
**registration_method** | **str** |  | 
**enabled** | **bool** |  | 
**lifecycle_state** | [**RuntimeProviderLifecycleState**](RuntimeProviderLifecycleState.md) |  | 
**availability_mode** | [**RuntimeProviderAvailabilityMode**](RuntimeProviderAvailabilityMode.md) |  | 
**accepted_contract_revision_id** | **str** |  | 
**active_config_revision_id** | **str** |  | 
**admin_version** | **int** |  | 
**capabilities** | **Dict[str, object]** |  | 
**config_schema** | **Dict[str, object]** |  | 
**metadata** | **Dict[str, object]** |  | 

## Example

```python
from azentsadminclient.models.runtime_provider_response import RuntimeProviderResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeProviderResponse from a JSON string
runtime_provider_response_instance = RuntimeProviderResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeProviderResponse.to_json())

# convert the object into a dict
runtime_provider_response_dict = runtime_provider_response_instance.to_dict()
# create an instance of RuntimeProviderResponse from a dict
runtime_provider_response_from_dict = RuntimeProviderResponse.from_dict(runtime_provider_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


