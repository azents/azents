# AgentToolkitListResponse

AgentToolkit list response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AgentToolkitResponse]**](AgentToolkitResponse.md) |  |

## Example

```python
from azentspublicclient.models.agent_toolkit_list_response import AgentToolkitListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentToolkitListResponse from a JSON string
agent_toolkit_list_response_instance = AgentToolkitListResponse.from_json(json)
# print the JSON string representation of the object
print(AgentToolkitListResponse.to_json())

# convert the object into a dict
agent_toolkit_list_response_dict = agent_toolkit_list_response_instance.to_dict()
# create an instance of AgentToolkitListResponse from a dict
agent_toolkit_list_response_from_dict = AgentToolkitListResponse.from_dict(agent_toolkit_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


