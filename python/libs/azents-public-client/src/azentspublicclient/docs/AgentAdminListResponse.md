# AgentAdminListResponse

AgentAdmin list response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**items** | [**List[AgentAdminResponse]**](AgentAdminResponse.md) |  |

## Example

```python
from azentspublicclient.models.agent_admin_list_response import AgentAdminListResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentAdminListResponse from a JSON string
agent_admin_list_response_instance = AgentAdminListResponse.from_json(json)
# print the JSON string representation of the object
print(AgentAdminListResponse.to_json())

# convert the object into a dict
agent_admin_list_response_dict = agent_admin_list_response_instance.to_dict()
# create an instance of AgentAdminListResponse from a dict
agent_admin_list_response_from_dict = AgentAdminListResponse.from_dict(agent_admin_list_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
