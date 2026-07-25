# ManagedMultiConnectionDisconnect

Sanitized terminal Multi App disconnect summary.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**disconnected_route_count** | **int** |  | 
**invalidated_default_count** | **int** |  | 
**expired_admission_count** | **int** |  | 
**expired_access_request_count** | **int** |  | 
**unavailable_resource_count** | **int** |  | 
**disconnected_binding_count** | **int** |  | 
**deleted_pending_context_count** | **int** |  | 

## Example

```python
from azentspublicclient.models.managed_multi_connection_disconnect import ManagedMultiConnectionDisconnect

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedMultiConnectionDisconnect from a JSON string
managed_multi_connection_disconnect_instance = ManagedMultiConnectionDisconnect.from_json(json)
# print the JSON string representation of the object
print(ManagedMultiConnectionDisconnect.to_json())

# convert the object into a dict
managed_multi_connection_disconnect_dict = managed_multi_connection_disconnect_instance.to_dict()
# create an instance of ManagedMultiConnectionDisconnect from a dict
managed_multi_connection_disconnect_from_dict = ManagedMultiConnectionDisconnect.from_dict(managed_multi_connection_disconnect_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


