# AgentAdminAddRequest

AgentAdmin add request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**workspace_user_id** | **str** | Workspace member ID to add |

## Example

```python
from azentspublicclient.models.agent_admin_add_request import AgentAdminAddRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentAdminAddRequest from a JSON string
agent_admin_add_request_instance = AgentAdminAddRequest.from_json(json)
# print the JSON string representation of the object
print(AgentAdminAddRequest.to_json())

# convert the object into a dict
agent_admin_add_request_dict = agent_admin_add_request_instance.to_dict()
# create an instance of AgentAdminAddRequest from a dict
agent_admin_add_request_from_dict = AgentAdminAddRequest.from_dict(agent_admin_add_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


