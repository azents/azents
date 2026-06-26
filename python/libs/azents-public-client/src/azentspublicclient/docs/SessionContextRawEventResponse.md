# SessionContextRawEventResponse

Session context raw event response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Event ID | 
**kind** | **str** | Event kind | 
**payload** | **Dict[str, object]** | Event payload | 
**external_id** | **str** |  | [optional] 
**adapter** | **str** |  | [optional] 
**provider** | **str** |  | [optional] 
**model** | **str** |  | [optional] 
**native_format** | **str** |  | [optional] 
**schema_version** | **str** | Schema version | 
**created_at** | **datetime** | Created time | 

## Example

```python
from azentspublicclient.models.session_context_raw_event_response import SessionContextRawEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionContextRawEventResponse from a JSON string
session_context_raw_event_response_instance = SessionContextRawEventResponse.from_json(json)
# print the JSON string representation of the object
print(SessionContextRawEventResponse.to_json())

# convert the object into a dict
session_context_raw_event_response_dict = session_context_raw_event_response_instance.to_dict()
# create an instance of SessionContextRawEventResponse from a dict
session_context_raw_event_response_from_dict = SessionContextRawEventResponse.from_dict(session_context_raw_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


