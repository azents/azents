# ExternalChannelMultiConnectionImpact

Sanitized deterministic impact projection for one whole Multi App.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**connection_id** | **str** |  | 
**generation** | **datetime** |  | 
**active_route_count** | **int** |  | 
**active_default_count** | **int** |  | 
**active_binding_count** | **int** |  | 
**bound_resource_count** | **int** |  | 
**open_admission_count** | **int** |  | 
**pending_access_request_count** | **int** |  | 
**pending_context_count** | **int** |  | 
**affected_defaults** | [**List[ExternalChannelMultiImpactDefault]**](ExternalChannelMultiImpactDefault.md) |  | 
**affected_bindings** | [**List[ExternalChannelMultiImpactBinding]**](ExternalChannelMultiImpactBinding.md) |  | 

## Example

```python
from azentspublicclient.models.external_channel_multi_connection_impact import ExternalChannelMultiConnectionImpact

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelMultiConnectionImpact from a JSON string
external_channel_multi_connection_impact_instance = ExternalChannelMultiConnectionImpact.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelMultiConnectionImpact.to_json())

# convert the object into a dict
external_channel_multi_connection_impact_dict = external_channel_multi_connection_impact_instance.to_dict()
# create an instance of ExternalChannelMultiConnectionImpact from a dict
external_channel_multi_connection_impact_from_dict = ExternalChannelMultiConnectionImpact.from_dict(external_channel_multi_connection_impact_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


