# ExternalChannelMultiImpactBinding

Sanitized active binding and Agent Session affected by one Multi mutation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**route_id** | **str** |  | 
**agent_session_id** | **str** |  | 
**resource_id** | **str** |  | 
**channel_label** | **str** |  | 
**thread_label** | **str** |  | 

## Example

```python
from azentspublicclient.models.external_channel_multi_impact_binding import ExternalChannelMultiImpactBinding

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelMultiImpactBinding from a JSON string
external_channel_multi_impact_binding_instance = ExternalChannelMultiImpactBinding.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelMultiImpactBinding.to_json())

# convert the object into a dict
external_channel_multi_impact_binding_dict = external_channel_multi_impact_binding_instance.to_dict()
# create an instance of ExternalChannelMultiImpactBinding from a dict
external_channel_multi_impact_binding_from_dict = ExternalChannelMultiImpactBinding.from_dict(external_channel_multi_impact_binding_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


