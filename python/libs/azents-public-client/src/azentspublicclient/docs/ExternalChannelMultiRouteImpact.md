# ExternalChannelMultiRouteImpact

Sanitized deterministic impact projection for one Multi App route.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**route_id** | **str** |  | 
**generation** | **datetime** |  | 
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
from azentspublicclient.models.external_channel_multi_route_impact import ExternalChannelMultiRouteImpact

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelMultiRouteImpact from a JSON string
external_channel_multi_route_impact_instance = ExternalChannelMultiRouteImpact.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelMultiRouteImpact.to_json())

# convert the object into a dict
external_channel_multi_route_impact_dict = external_channel_multi_route_impact_instance.to_dict()
# create an instance of ExternalChannelMultiRouteImpact from a dict
external_channel_multi_route_impact_from_dict = ExternalChannelMultiRouteImpact.from_dict(external_channel_multi_route_impact_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


