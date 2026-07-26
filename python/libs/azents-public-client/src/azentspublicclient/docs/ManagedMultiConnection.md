# ManagedMultiConnection

Redacted Workspace-owned Multi App connection projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**transport** | [**ExternalChannelTransport**](ExternalChannelTransport.md) |  | 
**app_mode** | [**ExternalChannelAppMode**](ExternalChannelAppMode.md) |  | 
**status** | [**ExternalChannelConnectionStatus**](ExternalChannelConnectionStatus.md) |  | 
**provider_app_id** | **str** |  | 
**provider_tenant_id** | **str** |  | 
**provider_bot_user_id** | **str** |  | 
**credentials_configured** | **bool** |  | 
**capabilities** | **Dict[str, object]** |  | 
**provider_config** | **Dict[str, object]** |  | 
**last_verified_at** | **datetime** |  | 
**last_health_at** | **datetime** |  | 
**socket_gap_detected_at** | **datetime** |  | 
**socket_gap_reason** | **str** |  | 
**disconnected_at** | **datetime** |  | 
**generation** | **datetime** |  | 
**active_agent_count** | **int** |  | 
**configured_default_count** | **int** |  | 

## Example

```python
from azentspublicclient.models.managed_multi_connection import ManagedMultiConnection

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedMultiConnection from a JSON string
managed_multi_connection_instance = ManagedMultiConnection.from_json(json)
# print the JSON string representation of the object
print(ManagedMultiConnection.to_json())

# convert the object into a dict
managed_multi_connection_dict = managed_multi_connection_instance.to_dict()
# create an instance of ManagedMultiConnection from a dict
managed_multi_connection_from_dict = ManagedMultiConnection.from_dict(managed_multi_connection_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


