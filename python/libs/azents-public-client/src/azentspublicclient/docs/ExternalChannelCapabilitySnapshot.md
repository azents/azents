# ExternalChannelCapabilitySnapshot

Redacted provider capabilities resolved for one connection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) | Provider | 
**transport** | [**ExternalChannelTransport**](ExternalChannelTransport.md) | Configured transport | 
**inbound_events** | **bool** | Whether inbound events are supported | 
**thread_history** | **bool** | Whether thread history can be collected | 
**post_messages** | **bool** | Whether messages can be posted | 
**update_messages** | **bool** | Whether owned messages can be updated | 
**delete_messages** | **bool** | Whether owned messages can be deleted | 

## Example

```python
from azentspublicclient.models.external_channel_capability_snapshot import ExternalChannelCapabilitySnapshot

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelCapabilitySnapshot from a JSON string
external_channel_capability_snapshot_instance = ExternalChannelCapabilitySnapshot.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelCapabilitySnapshot.to_json())

# convert the object into a dict
external_channel_capability_snapshot_dict = external_channel_capability_snapshot_instance.to_dict()
# create an instance of ExternalChannelCapabilitySnapshot from a dict
external_channel_capability_snapshot_from_dict = ExternalChannelCapabilitySnapshot.from_dict(external_channel_capability_snapshot_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


