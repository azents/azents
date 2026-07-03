# SessionInitializationEventResponse

Session initialization event response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | Session initialization event ID | 
**step_id** | **str** |  | [optional] 
**sequence** | **int** | Monotonic event sequence | 
**kind** | **str** | Event kind | 
**command_argv** | **List[str]** |  | [optional] 
**content** | **str** |  | [optional] 
**exit_code** | **int** |  | [optional] 
**created_at** | **datetime** | Created time | 

## Example

```python
from azentspublicclient.models.session_initialization_event_response import SessionInitializationEventResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionInitializationEventResponse from a JSON string
session_initialization_event_response_instance = SessionInitializationEventResponse.from_json(json)
# print the JSON string representation of the object
print(SessionInitializationEventResponse.to_json())

# convert the object into a dict
session_initialization_event_response_dict = session_initialization_event_response_instance.to_dict()
# create an instance of SessionInitializationEventResponse from a dict
session_initialization_event_response_from_dict = SessionInitializationEventResponse.from_dict(session_initialization_event_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


