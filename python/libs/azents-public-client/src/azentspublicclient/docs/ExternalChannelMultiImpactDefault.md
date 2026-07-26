# ExternalChannelMultiImpactDefault

Sanitized active channel default affected by one Multi mutation.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider_channel_id** | **str** |  | 
**route_id** | **str** |  | 
**agent_id** | **str** |  | 
**agent_name** | **str** |  | 

## Example

```python
from azentspublicclient.models.external_channel_multi_impact_default import ExternalChannelMultiImpactDefault

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelMultiImpactDefault from a JSON string
external_channel_multi_impact_default_instance = ExternalChannelMultiImpactDefault.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelMultiImpactDefault.to_json())

# convert the object into a dict
external_channel_multi_impact_default_dict = external_channel_multi_impact_default_instance.to_dict()
# create an instance of ExternalChannelMultiImpactDefault from a dict
external_channel_multi_impact_default_from_dict = ExternalChannelMultiImpactDefault.from_dict(external_channel_multi_impact_default_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


