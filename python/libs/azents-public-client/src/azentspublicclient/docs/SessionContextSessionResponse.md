# SessionContextSessionResponse

Session context session response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** | AgentSession ID | 
**agent_id** | **str** | Agent ID | 
**created_at** | **datetime** |  | [optional] 
**updated_at** | **datetime** |  | [optional] 

## Example

```python
from azentspublicclient.models.session_context_session_response import SessionContextSessionResponse

# TODO update the JSON string below
json = "{}"
# create an instance of SessionContextSessionResponse from a JSON string
session_context_session_response_instance = SessionContextSessionResponse.from_json(json)
# print the JSON string representation of the object
print(SessionContextSessionResponse.to_json())

# convert the object into a dict
session_context_session_response_dict = session_context_session_response_instance.to_dict()
# create an instance of SessionContextSessionResponse from a dict
session_context_session_response_from_dict = SessionContextSessionResponse.from_dict(session_context_session_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


