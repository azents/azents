# AgentSessionProjectDefaultsResponseItemsInner


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**type** | **str** | Workspace item type | [optional] [default to 'existing_project']
**path** | **str** | Existing Project path |
**source_project_path** | **str** | Source Project path |
**starting_ref** | **str** |  | [optional]

## Example

```python
from azentspublicclient.models.agent_session_project_defaults_response_items_inner import AgentSessionProjectDefaultsResponseItemsInner

# TODO update the JSON string below
json = "{}"
# create an instance of AgentSessionProjectDefaultsResponseItemsInner from a JSON string
agent_session_project_defaults_response_items_inner_instance = AgentSessionProjectDefaultsResponseItemsInner.from_json(json)
# print the JSON string representation of the object
print(AgentSessionProjectDefaultsResponseItemsInner.to_json())

# convert the object into a dict
agent_session_project_defaults_response_items_inner_dict = agent_session_project_defaults_response_items_inner_instance.to_dict()
# create an instance of AgentSessionProjectDefaultsResponseItemsInner from a dict
agent_session_project_defaults_response_items_inner_from_dict = AgentSessionProjectDefaultsResponseItemsInner.from_dict(agent_session_project_defaults_response_items_inner_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)
