# ManagedMultiRouteListResponse


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ManagedMultiRoute]**](ManagedMultiRoute.md) |  | 

## Example

```python
from azentspublicclient.models.managed_multi_route_list_response import ManagedMultiRouteListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ManagedMultiRouteListResponse from a JSON string
managed_multi_route_list_response_instance = ManagedMultiRouteListResponse.from_json(json)
# print the JSON string representation of the object
print(ManagedMultiRouteListResponse.to_json())

# convert the object into a dict
managed_multi_route_list_response_dict = managed_multi_route_list_response_instance.to_dict()
# create an instance of ManagedMultiRouteListResponse from a dict
managed_multi_route_list_response_from_dict = ManagedMultiRouteListResponse.from_dict(managed_multi_route_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


