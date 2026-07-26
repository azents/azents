# ManagedMultiRoute

One Multi App Agent catalog relationship.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**agent_id** | **str** |  | 
**agent_id_snapshot** | **str** |  | 
**agent_name** | **str** |  | 
**catalog_status** | [**ExternalChannelRouteCatalogStatus**](ExternalChannelRouteCatalogStatus.md) |  | 
**catalog_removed_at** | **datetime** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.managed_multi_route import ManagedMultiRoute

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedMultiRoute from a JSON string
managed_multi_route_instance = ManagedMultiRoute.from_json(json)
# print the JSON string representation of the object
print(ManagedMultiRoute.to_json())

# convert the object into a dict
managed_multi_route_dict = managed_multi_route_instance.to_dict()
# create an instance of ManagedMultiRoute from a dict
managed_multi_route_from_dict = ManagedMultiRoute.from_dict(managed_multi_route_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


