# JoinRequestResponse

Join request response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Join request ID |
**workspace_id** | **str** | Workspace ID |
**user_id** | **str** | Requesting user ID |
**message** | **str** |  |
**status** | [**JoinRequestStatus**](JoinRequestStatus.md) | Request status |
**created_at** | **datetime** | Created time |

## Example

```python
from azentspublicclient.models.join_request_response import JoinRequestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of JoinRequestResponse from a JSON string
join_request_response_instance = JoinRequestResponse.from_json(json)
# print the JSON string representation of the object
print(JoinRequestResponse.to_json())

# convert the object into a dict
join_request_response_dict = join_request_response_instance.to_dict()
# create an instance of JoinRequestResponse from a dict
join_request_response_from_dict = JoinRequestResponse.from_dict(join_request_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


