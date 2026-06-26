# MyJoinRequestResponse

My join request response schema.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Join request ID | 
**status** | [**JoinRequestStatus**](JoinRequestStatus.md) | Request status | 
**message** | **str** |  | 
**created_at** | **datetime** | Created time | 

## Example

```python
from azentspublicclient.models.my_join_request_response import MyJoinRequestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of MyJoinRequestResponse from a JSON string
my_join_request_response_instance = MyJoinRequestResponse.from_json(json)
# print the JSON string representation of the object
print(MyJoinRequestResponse.to_json())

# convert the object into a dict
my_join_request_response_dict = my_join_request_response_instance.to_dict()
# create an instance of MyJoinRequestResponse from a dict
my_join_request_response_from_dict = MyJoinRequestResponse.from_dict(my_join_request_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


