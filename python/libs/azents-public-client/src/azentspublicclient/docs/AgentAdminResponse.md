# AgentAdminResponse

AgentAdmin response.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**id** | **str** |  | 
**agent_id** | **str** |  | 
**workspace_user_id** | **str** |  | 
**created_at** | **datetime** |  | 

## Example

```python
from azentspublicclient.models.agent_admin_response import AgentAdminResponse

# TODO update the JSON string below
json = "{}"
# create an instance of AgentAdminResponse from a JSON string
agent_admin_response_instance = AgentAdminResponse.from_json(json)
# print the JSON string representation of the object
print(AgentAdminResponse.to_json())

# convert the object into a dict
agent_admin_response_dict = agent_admin_response_instance.to_dict()
# create an instance of AgentAdminResponse from a dict
agent_admin_response_from_dict = AgentAdminResponse.from_dict(agent_admin_response_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


