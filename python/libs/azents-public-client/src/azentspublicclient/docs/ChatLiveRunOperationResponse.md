# ChatLiveRunOperationResponse

Current live Run operation response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**kind** | **str** | Operation kind |
**operation_id** | **str** | Stable operation identity |
**status** | **str** | Current operation status |

## Example

```python
from azentspublicclient.models.chat_live_run_operation_response import ChatLiveRunOperationResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatLiveRunOperationResponse from a JSON string
chat_live_run_operation_response_instance = ChatLiveRunOperationResponse.from_json(json)
# print the JSON string representation of the object
print(ChatLiveRunOperationResponse.to_json())

# convert the object into a dict
chat_live_run_operation_response_dict = chat_live_run_operation_response_instance.to_dict()
# create an instance of ChatLiveRunOperationResponse from a dict
chat_live_run_operation_response_from_dict = ChatLiveRunOperationResponse.from_dict(chat_live_run_operation_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


