# ChatWriteAcceptedResponse

REST write accepted target.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Accepted target type |
**id** | **str** | Accepted target ID |

## Example

```python
from azentspublicclient.models.chat_write_accepted_response import ChatWriteAcceptedResponse

# TODO update the JSON string below
json = "{}"
# create an instance of ChatWriteAcceptedResponse from a JSON string
chat_write_accepted_response_instance = ChatWriteAcceptedResponse.from_json(json)
# print the JSON string representation of the object
print(ChatWriteAcceptedResponse.to_json())

# convert the object into a dict
chat_write_accepted_response_dict = chat_write_accepted_response_instance.to_dict()
# create an instance of ChatWriteAcceptedResponse from a dict
chat_write_accepted_response_from_dict = ChatWriteAcceptedResponse.from_dict(chat_write_accepted_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


