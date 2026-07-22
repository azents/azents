# ExternalChannelConnectionStatusSnapshot

Redacted current connection status for service and future API projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**status** | [**ExternalChannelConnectionStatus**](ExternalChannelConnectionStatus.md) | Current operational status | 
**code** | **str** |  | 
**message** | **str** |  | 
**action_hint** | **str** |  | 
**checked_at** | **datetime** |  | 
**identity** | [**ExternalChannelProviderIdentity**](ExternalChannelProviderIdentity.md) |  | 
**credentials** | [**ExternalChannelCredentialSnapshot**](ExternalChannelCredentialSnapshot.md) | Redacted credential configuration state | 
**capabilities** | [**ExternalChannelCapabilitySnapshot**](ExternalChannelCapabilitySnapshot.md) |  | 

## Example

```python
from azentspublicclient.models.external_channel_connection_status_snapshot import ExternalChannelConnectionStatusSnapshot

# TODO update the JSON string below
json = "{}"
# create an instance of ExternalChannelConnectionStatusSnapshot from a JSON string
external_channel_connection_status_snapshot_instance = ExternalChannelConnectionStatusSnapshot.from_json(json)
# print the JSON string representation of the object
print(ExternalChannelConnectionStatusSnapshot.to_json())

# convert the object into a dict
external_channel_connection_status_snapshot_dict = external_channel_connection_status_snapshot_instance.to_dict()
# create an instance of ExternalChannelConnectionStatusSnapshot from a dict
external_channel_connection_status_snapshot_from_dict = ExternalChannelConnectionStatusSnapshot.from_dict(external_channel_connection_status_snapshot_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


