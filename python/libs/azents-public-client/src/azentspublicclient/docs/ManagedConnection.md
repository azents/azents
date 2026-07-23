# ManagedConnection


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**route_id** | **str** |  | 
**agent_id** | **str** |  | 
**provider** | [**ExternalChannelProvider**](ExternalChannelProvider.md) |  | 
**transport** | [**ExternalChannelTransport**](ExternalChannelTransport.md) |  | 
**status** | [**ExternalChannelConnectionStatus**](ExternalChannelConnectionStatus.md) |  | 
**provider_app_id** | **str** |  | 
**provider_tenant_id** | **str** |  | 
**provider_bot_user_id** | **str** |  | 
**credentials_configured** | **bool** |  | 
**capabilities** | **Dict[str, object]** |  | 
**last_verified_at** | **datetime** |  | 
**last_health_at** | **datetime** |  | 
**socket_gap_detected_at** | **datetime** |  | 
**socket_gap_reason** | **str** |  | 
**disconnected_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_connection import ManagedConnection

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedConnection from a JSON string
managed_connection_instance = ManagedConnection.from_json(json)
# print the JSON string representation of the object
print(ManagedConnection.to_json())

# convert the object into a dict
managed_connection_dict = managed_connection_instance.to_dict()
# create an instance of ManagedConnection from a dict
managed_connection_from_dict = ManagedConnection.from_dict(managed_connection_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


