# MultiRouteCreateRequest


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** |  | 

## Example

```python
from azentspublicclient.models.multi_route_create_request import MultiRouteCreateRequest

# TODO update the JSON string below
json = "{}"
# create an instance of MultiRouteCreateRequest from a JSON string
multi_route_create_request_instance = MultiRouteCreateRequest.from_json(json)
# print the JSON string representation of the object
print(MultiRouteCreateRequest.to_json())

# convert the object into a dict
multi_route_create_request_dict = multi_route_create_request_instance.to_dict()
# create an instance of MultiRouteCreateRequest from a dict
multi_route_create_request_from_dict = MultiRouteCreateRequest.from_dict(multi_route_create_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


