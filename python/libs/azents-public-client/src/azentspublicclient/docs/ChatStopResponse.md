# ChatStopResponse

REST stop response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** | AgentSession ID |

## Example

```python
from azentspublicclient.models.chat_stop_response import ChatStopResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatStopResponse from a JSON string
chat_stop_response_instance = ChatStopResponse.from_json(json)
# print the JSON string representation of the object
print(ChatStopResponse.to_json())

# convert the object into a dict
chat_stop_response_dict = chat_stop_response_instance.to_dict()
# create an instance of ChatStopResponse from a dict
chat_stop_response_from_dict = ChatStopResponse.from_dict(chat_stop_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
