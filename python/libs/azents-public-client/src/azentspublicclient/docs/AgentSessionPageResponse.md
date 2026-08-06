# AgentSessionPageResponse

Bounded Agent session directory response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AgentSessionResponse]**](AgentSessionResponse.md) | Session page items | 
**total_count** | **int** | Matching root-session count | 
**offset** | **int** | Zero-based item offset | 
**limit** | **int** | Requested page size | 
**current_archive_retention_days** | **int** |  | 

## Example

```python
from azentspublicclient.models.agent_session_page_response import AgentSessionPageResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionPageResponse from a JSON string
agent_session_page_response_instance = AgentSessionPageResponse.from_json(json)
# print the JSON string representation of the object
print(AgentSessionPageResponse.to_json())

# convert the object into a dict
agent_session_page_response_dict = agent_session_page_response_instance.to_dict()
# create an instance of AgentSessionPageResponse from a dict
agent_session_page_response_from_dict = AgentSessionPageResponse.from_dict(agent_session_page_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


