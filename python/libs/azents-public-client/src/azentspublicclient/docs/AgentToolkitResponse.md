# AgentToolkitResponse

AgentToolkit response model.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  |
**agent_id** | **str** |  |
**toolkit_id** | **str** |  |
**toolkit_type** | **str** |  |
**created_at** | **datetime** |  |

## Example

```python
from azentspublicclient.models.agent_toolkit_response import AgentToolkitResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentToolkitResponse from a JSON string
agent_toolkit_response_instance = AgentToolkitResponse.from_json(json)
# print the JSON string representation of the object
print(AgentToolkitResponse.to_json())

# convert the object into a dict
agent_toolkit_response_dict = agent_toolkit_response_instance.to_dict()
# create an instance of AgentToolkitResponse from a dict
agent_toolkit_response_from_dict = AgentToolkitResponse.from_dict(agent_toolkit_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
