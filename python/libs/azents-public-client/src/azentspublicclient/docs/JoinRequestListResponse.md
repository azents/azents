# JoinRequestListResponse

Join request list response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[JoinRequestResponse]**](JoinRequestResponse.md) | Join request list |
**total** | **int** | Total count |

## Example

```python
from azentspublicclient.models.join_request_list_response import JoinRequestListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of JoinRequestListResponse from a JSON string
join_request_list_response_instance = JoinRequestListResponse.from_json(json)
# print the JSON string representation of the object
print(JoinRequestListResponse.to_json())

# convert the object into a dict
join_request_list_response_dict = join_request_list_response_instance.to_dict()
# create an instance of JoinRequestListResponse from a dict
join_request_list_response_from_dict = JoinRequestListResponse.from_dict(join_request_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


