# RuntimeWebRequestResponse

Durable exposure request projection.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**requester_kind** | [**RuntimeWebRequesterKind**](RuntimeWebRequesterKind.md) |  | 
**state** | [**RuntimeWebRequestState**](RuntimeWebRequestState.md) |  | 
**revision** | **int** |  | 
**label** | **str** |  | 
**decided_by_user_id** | **str** |  | 
**decided_at** | **datetime** |  | 
**created_at** | **datetime** |  | 
**updated_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.runtime_web_request_response import RuntimeWebRequestResponse

# TODO update the JSON string below
json = "{}"
# create an instance of RuntimeWebRequestResponse from a JSON string
runtime_web_request_response_instance = RuntimeWebRequestResponse.from_json(json)
# print the JSON string representation of the object
print(RuntimeWebRequestResponse.to_json())

# convert the object into a dict
runtime_web_request_response_dict = runtime_web_request_response_instance.to_dict()
# create an instance of RuntimeWebRequestResponse from a dict
runtime_web_request_response_from_dict = RuntimeWebRequestResponse.from_dict(runtime_web_request_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


