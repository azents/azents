# PartialHistoryResponse

Partial history live projection response to compose into Chat timeline.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[ChatEventResponse]**](ChatEventResponse.md) | Partial history event projection list |

## Example

```python
from azentspublicclient.models.partial_history_response import PartialHistoryResponse

# TODO update the JSON string below
json = "{}"
# create an instance of PartialHistoryResponse from a JSON string
partial_history_response_instance = PartialHistoryResponse.from_json(json)
# print the JSON string representation of the object
print(PartialHistoryResponse.to_json())

# convert the object into a dict
partial_history_response_dict = partial_history_response_instance.to_dict()
# create an instance of PartialHistoryResponse from a dict
partial_history_response_from_dict = PartialHistoryResponse.from_dict(partial_history_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
