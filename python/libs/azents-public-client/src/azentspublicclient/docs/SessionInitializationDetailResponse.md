# SessionInitializationDetailResponse

Durable session initialization detail response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**initialization** | [**SessionInitializationResponse**](SessionInitializationResponse.md) | Initialization projection | 
**events** | [**List[SessionInitializationEventResponse]**](SessionInitializationEventResponse.md) | Initialization event list | 

## Example

```python
from azentspublicclient.models.session_initialization_detail_response import SessionInitializationDetailResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionInitializationDetailResponse from a JSON string
session_initialization_detail_response_instance = SessionInitializationDetailResponse.from_json(json)
# print the JSON string representation of the object
print(SessionInitializationDetailResponse.to_json())

# convert the object into a dict
session_initialization_detail_response_dict = session_initialization_detail_response_instance.to_dict()
# create an instance of SessionInitializationDetailResponse from a dict
session_initialization_detail_response_from_dict = SessionInitializationDetailResponse.from_dict(session_initialization_detail_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


