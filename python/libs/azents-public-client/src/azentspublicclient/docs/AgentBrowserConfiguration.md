# AgentBrowserConfiguration


## Properties

Name | Type | Description | Notes
------------ | ------------- | ------------- | -------------
**agent_id** | **str** |  | 
**intent_id** | **str** |  | 
**requested** | [**BrowserImplementation**](BrowserImplementation.md) |  | 
**applied** | [**BrowserImplementation**](BrowserImplementation.md) |  | 
**state** | **str** |  | 
**reason_code** | **str** |  | 
**runtime_id** | **str** |  | 
**runner_generation** | **int** |  | 

## Example

```python
from azentspublicclient.models.agent_browser_configuration import AgentBrowserConfiguration

# TODO update the JSON string below
json = "{}"
# create an instance of AgentBrowserConfiguration from a JSON string
agent_browser_configuration_instance = AgentBrowserConfiguration.from_json(json)
# print the JSON string representation of the object
print(AgentBrowserConfiguration.to_json())

# convert the object into a dict
agent_browser_configuration_dict = agent_browser_configuration_instance.to_dict()
# create an instance of AgentBrowserConfiguration from a dict
agent_browser_configuration_from_dict = AgentBrowserConfiguration.from_dict(agent_browser_configuration_dict)
```
[[Back to Model list]](../README.md#documentation-for-models) [[Back to API list]](../README.md#documentation-for-api-endpoints) [[Back to README]](../README.md)


