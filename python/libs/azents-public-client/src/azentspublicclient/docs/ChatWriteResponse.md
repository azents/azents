# ChatWriteResponse

REST chat write response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**session_id** | **str** | AgentSession ID |
**client_request_id** | **str** | Client-generated idempotency key |
**accepted** | [**ChatWriteAcceptedResponse**](ChatWriteAcceptedResponse.md) | Accepted write target |
**snapshot** | [**ChatWriteSnapshotResponse**](ChatWriteSnapshotResponse.md) | Authoritative live snapshot after commit |
**history_reload_required** | **bool** | Whether durable history reload is needed |

## Example

```python
from azentspublicclient.models.chat_write_response import ChatWriteResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatWriteResponse from a JSON string
chat_write_response_instance = ChatWriteResponse.from_json(json)
# print the JSON string representation of the object
print(ChatWriteResponse.to_json())

# convert the object into a dict
chat_write_response_dict = chat_write_response_instance.to_dict()
# create an instance of ChatWriteResponse from a dict
chat_write_response_from_dict = ChatWriteResponse.from_dict(chat_write_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


