# AgentToolkitAttachRequest

AgentToolkit attach request.

## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**toolkit_id** | **str** | Toolkit ID to attach | 

## Example

```python
from azentspublicclient.models.agent_toolkit_attach_request import AgentToolkitAttachRequest

# TODO update the JSON string below
json = "{}"
# create an instance of AgentToolkitAttachRequest from a JSON string
agent_toolkit_attach_request_instance = AgentToolkitAttachRequest.from_json(json)
# print the JSON string representation of the object
print(AgentToolkitAttachRequest.to_json())

# convert the object into a dict
agent_toolkit_attach_request_dict = agent_toolkit_attach_request_instance.to_dict()
# create an instance of AgentToolkitAttachRequest from a dict
agent_toolkit_attach_request_from_dict = AgentToolkitAttachRequest.from_dict(agent_toolkit_attach_request_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


